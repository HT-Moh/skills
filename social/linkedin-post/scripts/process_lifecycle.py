"""Linux synchronous process-tree ownership, cancellation and bounded teardown.

This is a dedicated-CLI scope, not a general concurrent process pool. Launch all
children with spawn(). Delegated cgroup v2 contains complete trees when available.
Without delegation, fallback requires a clean CLI with no preexisting descendants;
only then can new/subreaper-adopted descendants be attributed to this scope.
pidfds, never PID/PGID signals, protect against ID reuse.
"""
import contextlib
import ctypes
import os
import select
import signal
import subprocess
import time
from process_cgroup import OwnedCgroup

MAX_PROCESSES = 4096
KILL_GRACE = 2
_scopes = []
_critical_depth = 0
_cancelled = None


class CleanupError(RuntimeError):
    def __init__(self, errors):
        self.errors = list(dict.fromkeys(str(error) for error in errors))
        super().__init__("process teardown incomplete: " + "; ".join(self.errors))


def _cancel(signum, frame):
    global _cancelled
    _cancelled = signum
    if not _critical_depth:
        raise SystemExit(128 + signum)


@contextlib.contextmanager
def defer_cancellation(*, cleanup=False):
    global _critical_depth
    _critical_depth += 1
    try:
        yield
    finally:
        _critical_depth -= 1
        if not cleanup and not _critical_depth and _cancelled is not None:
            raise SystemExit(128 + _cancelled)


def current_scope():
    if not _scopes:
        raise RuntimeError("process launch requires an owned lifecycle")
    return _scopes[-1]


def _read_at(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        return stream.read(1024 * 1024)


def _stat(directory):
    fields = _read_at(directory, "stat").rsplit(b")", 1)[1].split()
    return int(fields[1]), int(fields[19])  # ppid, starttime (clock ticks)


class ProcessHandle:
    """An anchored proc directory plus pidfd for one verified process generation."""
    def __init__(self, pid, process=None):
        self.pid = pid
        self.process = process
        self.directory = os.open(f"/proc/{pid}", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.pidfd = None
        try:
            before = _stat(self.directory)
            self.pidfd = os.pidfd_open(pid)
            after = _stat(self.directory)
            # The second read uses the *same proc inode*. If the original process
            # was reaped while pidfd_open raced PID reuse, this read fails.
            if before[1] != after[1]:
                raise ProcessLookupError("process changed during pidfd capture")
            self.parent, self.starttime = after
        except BaseException:
            self.close()
            raise

    @property
    def identity(self):
        return self.pid, self.starttime

    def same_process(self):
        try:
            return os.stat(f"/proc/{self.pid}").st_ino == os.fstat(self.directory).st_ino
        except FileNotFoundError:
            return False

    def exited(self):
        return bool(select.select([self.pidfd], [], [], 0)[0])

    def send_signal(self, signum):
        if self.exited():
            return
        try:
            signal.pidfd_send_signal(self.pidfd, signum)
        except ProcessLookupError:
            pass

    def reap(self):
        if not self.exited():
            return
        try:
            info = os.waitid(os.P_PIDFD, self.pidfd, os.WEXITED | os.WNOHANG)
        except ChildProcessError:
            return  # already reaped by Popen, or still another process's child
        if info is not None and self.process is not None:
            self.process.returncode = (info.si_status if info.si_code == os.CLD_EXITED
                                       else -info.si_status)

    def children(self):
        task_fd = os.open("task", os.O_RDONLY | os.O_DIRECTORY, dir_fd=self.directory)
        try:
            tids = os.listdir(task_fd)
        finally:
            os.close(task_fd)
        children = set()
        for tid in tids:
            try:
                children.update(map(int, _read_at(self.directory, f"task/{tid}/children").split()))
            except (FileNotFoundError, ProcessLookupError):
                continue
        return children

    def close(self):
        errors = []
        for name in ("pidfd", "directory"):
            fd = getattr(self, name)
            if fd is not None:
                try:
                    os.close(fd)
                except OSError as exc:
                    errors.append(exc)
                finally:
                    setattr(self, name, None)
        if errors:
            raise CleanupError(errors)


class ProcessScope:
    """Own new descendants; attempt every cleanup using shared phase deadlines."""
    def __init__(self, *, grace=10, kill_grace=KILL_GRACE, use_cgroup=True):
        self.grace = grace
        self.kill_grace = kill_grace
        self.owned = {}
        self.retired = []
        self.processes = []
        self.identities = set()
        self.errors = []
        self.stopped = False
        self.root = None
        self.cgroup = None
        self.use_cgroup = use_cgroup

    def __enter__(self):
        global _cancelled
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.previous_subreaper = ctypes.c_int()
        if self.libc.prctl(37, ctypes.byref(self.previous_subreaper), 0, 0, 0) \
                or self.libc.prctl(36, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), "cannot own process descendants")
        self.handlers = {}
        try:
            if not _scopes:
                _cancelled = None
                for sig in (signal.SIGTERM, signal.SIGINT):
                    self.handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, _cancel)
            self.root = ProcessHandle(os.getpid())
            if self.use_cgroup:
                parent = _scopes[-1].cgroup.path if _scopes and _scopes[-1].cgroup else None
                self.cgroup = OwnedCgroup.create(parent)
            if self.cgroup is None and self.root.children():
                # No snapshot/recheck can safely attribute an unseen orphan from
                # a preexisting tree that forks/exits between observations.
                # Refuse before launching anything, including nested fallback
                # calls while a parent scope still owns live children.
                raise RuntimeError("fallback requires no preexisting descendants")
            _scopes.append(self)
            return self
        except BaseException:
            self._release()
            raise

    def _remember(self, handle):
        old = self.owned.get(handle.pid)
        if old is not None and old is not handle:
            self.retired.append(old)
        self.owned[handle.pid] = handle
        self.identities.add(handle.identity)

    def refresh(self):
        """Walk anchored descendants, including new children adopted by subreaping."""
        if self.cgroup is not None:
            self._refresh_cgroup()
            return
        queue = [self.root]
        visited = set()
        while queue:
            parent = queue.pop()
            try:
                children = parent.children()
            except (FileNotFoundError, ProcessLookupError):
                continue
            for pid in children:
                if pid in visited:
                    continue
                visited.add(pid)
                if len(visited) > MAX_PROCESSES:
                    raise RuntimeError("process discovery limit exceeded")
                known = self.owned.get(pid)
                handle = known
                try:
                    if known is None or not known.same_process():
                        handle = ProcessHandle(pid)
                    ppid, _ = _stat(handle.directory)
                    if ppid != parent.pid:
                        if handle is not known:
                            handle.close()
                        continue
                except (FileNotFoundError, ProcessLookupError):
                    if handle is not None and handle is not known:
                        handle.close()
                    continue
                self._remember(handle)
                queue.append(handle)

    def _refresh_cgroup(self):
        # cgroup.procs may omit zombies. Include direct subreaper adoptees too,
        # but admit only generations whose anchored proc cgroup proves ownership.
        pids = self.cgroup.members() | self.root.children()
        if len(pids) > MAX_PROCESSES:
            raise RuntimeError("process discovery limit exceeded")
        for pid in pids:
            known = self.owned.get(pid)
            handle = known
            try:
                if known is None or not known.same_process():
                    handle = ProcessHandle(pid)
                if self.cgroup.contains(_read_at(handle.directory, "cgroup")):
                    self._remember(handle)
                elif handle is not known:
                    handle.close()
            except (FileNotFoundError, ProcessLookupError):
                if handle is not None and handle is not known:
                    handle.close()

    def spawn(self, *args, **kwargs):
        """Record a direct child's pidfd before cancellation can unwind its caller."""
        with defer_cancellation():
            if self.cgroup is not None:
                if "preexec_fn" in kwargs:
                    raise ValueError("owned spawn reserves preexec_fn for cgroup placement")
                kwargs["preexec_fn"] = self.cgroup.attach_before_exec
            proc = subprocess.Popen(*args, **kwargs)
            self.processes.append(proc)
            handle = ProcessHandle(proc.pid, proc)
            self._remember(handle)
        return proc

    def stop(self):
        """Use shared cooperative deadlines, not hard bounds on blocking kernel I/O."""
        if self.stopped:
            return
        self.stopped = True
        with defer_cancellation(cleanup=True):
            errors = set()
            for signum, duration in ((signal.SIGTERM, self.grace),
                                     (signal.SIGKILL, self.kill_grace)):
                deadline = time.monotonic() + duration
                sent = set()
                if signum == signal.SIGKILL and self.cgroup is not None:
                    try:
                        self.cgroup.kill()
                    except Exception as exc:
                        errors.add(str(exc))  # still attempt every pidfd independently
                while True:
                    try:
                        self.refresh()
                    except Exception as exc:
                        errors.add(str(exc))
                    for handle in list(self.owned.values()):
                        try:
                            # Never signal a retired/exited process, even if a
                            # different process now occupies its numerical PID.
                            if not handle.exited() and handle not in sent:
                                handle.send_signal(signum)
                                sent.add(handle)
                            handle.reap()
                        except Exception as exc:
                            errors.add(str(exc))
                            sent.add(handle)
                    remaining = self._live(errors)
                    if not remaining:
                        # A parent's death may have adopted children during this
                        # pass. Discover once more before declaring the tree empty.
                        try:
                            self.refresh()
                        except Exception as exc:
                            errors.add(str(exc))
                        remaining = self._live(errors)
                        for handle in self.owned.values():
                            try:
                                handle.reap()
                            except Exception as exc:
                                errors.add(str(exc))
                        if not remaining:
                            break
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(.01)
            survivors = [h.identity for h in self._live(errors)]
            if survivors:
                errors.add(f"owned processes remain alive: {survivors}")
            self.errors.extend(errors)
            self._close_pipes()
            if self.errors:
                raise CleanupError(self.errors)

    def _live(self, errors):
        remaining = []
        for handle in self.owned.values():
            try:
                if not handle.exited():
                    remaining.append(handle)
            except Exception as exc:
                errors.add(str(exc))
                remaining.append(handle)  # unknown state is not proof of exit
        return remaining

    def _close_pipes(self):
        # Independent of signal, wait and other stream-close failures.
        for proc in self.processes:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception as exc:
                        self.errors.append(exc)

    def _release(self):
        for handle in [*self.owned.values(), *self.retired, self.root]:
            if handle is not None:
                try:
                    handle.close()
                except Exception as exc:
                    self.errors.append(exc)
        if self.cgroup is not None:
            try:
                self.cgroup.remove()
            except Exception as exc:
                self.errors.append(exc)
        for sig, handler in self.handlers.items():
            try:
                signal.signal(sig, handler)
            except Exception as exc:
                self.errors.append(exc)
        if self.libc.prctl(36, self.previous_subreaper.value, 0, 0, 0):
            self.errors.append("cannot restore subreaper state")

    def __exit__(self, typ, value, traceback):
        global _cancelled
        with defer_cancellation(cleanup=True):
            try:
                self.stop()
            except CleanupError:
                pass  # aggregate after independently releasing every handle
            except Exception as exc:
                self.errors.append(exc)
            finally:
                self._close_pipes()
                _scopes.pop()
                self._release()
            cancelled = _cancelled
            if not _scopes:
                _cancelled = None
        if self.errors:
            if isinstance(value, CleanupError):
                self.errors.extend(value.errors)
            raise CleanupError(self.errors) from value
        if cancelled is not None and typ is None and not _scopes:
            raise SystemExit(128 + cancelled)
