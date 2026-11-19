"""Linux synchronous process-tree ownership, cancellation and bounded teardown.

This is a dedicated-CLI scope, not a general concurrent process pool. Launch all
children with spawn(). Delegated cgroup v2 contains complete trees when available.
Without delegation, fallback requires a clean CLI with no preexisting descendants;
only then can new/subreaper-adopted descendants be attributed to this scope.
pidfds, never PID/PGID signals, protect against ID reuse.
"""
import contextlib
import ctypes
from dataclasses import dataclass
import os
import select
import signal
import subprocess
import time
from process_cgroup import OwnedCgroup
from capture_control import CleanupContext, CleanupPolicy, OMITTED

MAX_PROCESSES = 4096
KILL_GRACE = 2
_scopes = []
_critical_depth = 0
_cancelled = None
_cancelled_at = None
_entering_capture = None


class CleanupError(RuntimeError):
    def __init__(self, errors):
        self.errors = list(dict.fromkeys(str(error) for error in errors))
        super().__init__("process teardown incomplete: " + "; ".join(self.errors))


@dataclass(frozen=True)
class CleanupDisposition:
    """Explicit failed/unknown teardown carried through cancellation unwinding."""
    errors: tuple[str, ...]


def cleanup_failure(value):
    """Read only our typed handoff, never arbitrary exception cause/context chains."""
    disposition = getattr(value, "_publisher_cleanup", None)
    if isinstance(disposition, CleanupDisposition):
        return CleanupError(disposition.errors)
    if isinstance(value, CleanupError):
        return value
    return None


def retain_cleanup_failure(interrupt, error):
    """Preserve the primary exception's identity and accumulate owner failures."""
    previous = cleanup_failure(interrupt)
    current = cleanup_failure(error)
    combined = CleanupError([*(previous.errors if previous else []),
                             *(current.errors if current else [error])])
    interrupt._publisher_cleanup = CleanupDisposition(tuple(combined.errors))
    if isinstance(interrupt, CleanupError):
        # The raised primary remains the same object. Keep its public diagnostics
        # consistent with the authoritative typed secondary aggregate.
        interrupt.errors = list(combined.errors)
        interrupt.args = combined.args
    return combined


def _cancel(signum, frame):
    global _cancelled, _cancelled_at
    if _cancelled is None:
        _cancelled = SystemExit(128 + signum)
        _cancelled_at = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    if _entering_capture is not None or (_scopes and _scopes[-1].capture_deadline is not None):
        return  # Capture handlers only latch; ordinary checkpoints publish and raise.
    if not _critical_depth:
        raise _cancelled


def cancellation_checkpoint(*, cleanup=False):
    if _cancelled is not None:
        if (_scopes and _scopes[-1].capture_context is not None and
                _scopes[-1].capture_context.fd is not None):
            _scopes[-1].capture_context.begin(abort=True, at=_cancelled_at)
        if not cleanup:
            raise _cancelled


@contextlib.contextmanager
def defer_cancellation(*, cleanup=False):
    global _critical_depth
    _critical_depth += 1
    try:
        yield
    finally:
        _critical_depth -= 1
        if not cleanup and not _critical_depth and _cancelled is not None:
            raise _cancelled


def current_scope():
    if not _scopes:
        raise RuntimeError("process launch requires an owned lifecycle")
    return _scopes[-1]


def capture_owner() -> "ProcessScope | None":
    """The existing process root retains at most one profile lease until control closes."""
    return next((scope for scope in _scopes if scope.owns_context), None)


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
    def __init__(self, *, grace=OMITTED, kill_grace=OMITTED, use_cgroup=True,
                  capture_deadline=None, outer_capture=False, capture_context=None,
                  auxiliary=False):
        self.grace = 10 if grace is OMITTED else grace
        self.kill_grace = KILL_GRACE if kill_grace is OMITTED else kill_grace
        self.owned = {}
        self.retired = []
        self.processes = []
        self.identities = set()
        self.errors = []
        self.stopped = False
        self.root = None
        self.cgroup = None
        self.use_cgroup = use_cgroup
        inherited = _scopes[-1].capture_deadline if _scopes else None
        if inherited is not None and capture_deadline is not None and inherited.expiry != capture_deadline.expiry:
            raise ValueError("nested capture deadline changed")
        self.capture_deadline = capture_deadline or inherited
        borrowed = _scopes[-1].capture_context if _scopes else None
        if borrowed is not None and capture_context is not None and borrowed is not capture_context:
            raise ValueError("nested capture context changed")
        self.capture_context = capture_context or borrowed
        self.owns_context = borrowed is None and self.capture_deadline is not None
        self.auxiliary = auxiliary
        if self.capture_deadline is not None:
            if self.capture_context is not None:
                if self.capture_context.expiry != self.capture_deadline.expiry:
                    raise ValueError("nested capture deadline changed")
                if not auxiliary:
                    try:
                        self.capture_context.policy.require(grace, kill_grace)
                    except ValueError:
                        self.capture_context.begin(abort=True)
                        raise
                self.capture_policy = self.capture_context.policy
            else:
                self.capture_policy = CleanupPolicy.normalize(
                    grace=OMITTED if auxiliary else grace,
                    kill_grace=OMITTED if auxiliary else kill_grace)
            if not auxiliary:
                self.grace = self.capture_policy.term_ns / 1e9
                self.kill_grace = self.capture_policy.kill_ns / 1e9
        self.escalated = False
        self.outer_capture = outer_capture
        self.cleanup_cutoffs = None
        self.handlers = {}
        self.libc = None
        self.previous_subreaper = None
        self.capture_lease = None
        self.lease_failure: BaseException | None = None

    def _ensure_context(self):
        if self.capture_deadline is not None and self.capture_context is None:
            self.capture_context = CleanupContext.create(self.capture_deadline.expiry, self.capture_policy)

    def check_work(self):
        cancellation_checkpoint()
        if self.capture_context is not None:
            return self.capture_context.check()

    def phase_cutoff(self, duration: float, reserve: int) -> int:
        cutoff = time.clock_gettime_ns(time.CLOCK_MONOTONIC) + int(duration * 1_000_000_000)
        if self.capture_deadline is not None:
            cutoff = min(cutoff, self.capture_deadline.expiry - reserve * 1_000_000_000)
        return cutoff

    def begin_cleanup(self, *, abort=False):
        """One budget for observation and teardown, never restarted by stop().

        The supervisor observes the worker's TERM/KILL opportunity before its
        own outer fallback. Nested worker scopes retain publisher D-5/D-3 limits.
        """
        if self.capture_deadline is not None:
            self._ensure_context()
            cancellation_checkpoint(cleanup=True)
            t, k, o = self.capture_context.begin(abort=abort, at=_cancelled_at)
            self.cleanup_cutoffs = (k, o) if self.outer_capture else (t, k)
            return self.cleanup_cutoffs
        if self.cleanup_cutoffs is None:
            now = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
            term_duration = self.grace + (self.kill_grace if self.outer_capture else 0)
            term = now + int(term_duration * 1_000_000_000)
            term_reserve, kill_reserve = (3, 0) if self.outer_capture else (5, 3)
            if self.capture_deadline is not None:
                term = min(term, self.capture_deadline.expiry - term_reserve * 1_000_000_000)
            kill = max(now, term) + int(self.kill_grace * 1_000_000_000)
            if self.capture_deadline is not None:
                kill = min(kill, self.capture_deadline.expiry - kill_reserve * 1_000_000_000)
            self.cleanup_cutoffs = term, kill
        return self.cleanup_cutoffs

    def __enter__(self):
        global _cancelled, _cancelled_at, _entering_capture
        previous_entering = _entering_capture
        self.owns_cancellation = not _scopes and previous_entering is None
        try:
            if self.owns_cancellation:
                _cancelled = None
                _cancelled_at = None
                _entering_capture = self if self.capture_deadline is not None else None
                for sig in (signal.SIGTERM, signal.SIGINT):
                    self.handlers[sig] = signal.getsignal(sig)
                    signal.signal(sig, _cancel)
            self._ensure_context()
            cancellation_checkpoint()
            self.libc = ctypes.CDLL(None, use_errno=True)
            previous = ctypes.c_int()
            if self.libc.prctl(37, ctypes.byref(previous), 0, 0, 0):
                raise OSError(ctypes.get_errno(), "cannot read subreaper state")
            self.previous_subreaper = previous
            if self.libc.prctl(36, 1, 0, 0, 0):
                raise OSError(ctypes.get_errno(), "cannot own process descendants")
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
        except BaseException as value:
            release_interrupt = None
            with defer_cancellation(cleanup=True):
                try:
                    self._release(value)
                except BaseException as exc:
                    self.errors.append(exc)
                    if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                        release_interrupt = exc
                finally:
                    try:
                        self._restore_handlers()
                    finally:
                        cancelled = _cancelled
                        if self.owns_cancellation:
                            _cancelled = _cancelled_at = None
            primary = value if isinstance(value, (SystemExit, KeyboardInterrupt)) else (
                cancelled or release_interrupt or value)
            if primary is not value:
                retain_cleanup_failure(primary, value)
            if self.errors:
                raise primary from retain_cleanup_failure(primary, CleanupError(self.errors))
            if primary is value:
                raise
            raise primary from value
        finally:
            _entering_capture = previous_entering

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
        if self.capture_deadline is not None:
            self.check_work()
            self.capture_deadline.remaining()
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
            skip_epoch = False
            if self.capture_deadline is not None and self.auxiliary and not self.errors:
                self.refresh()
                skip_epoch = (all(p.poll() == 0 for p in self.processes) and
                              not self._live(errors) and not errors and _cancelled is None)
            cutoffs = self.begin_cleanup() if self.capture_deadline is not None and not skip_epoch else None
            for signum, duration in ((signal.SIGTERM, self.grace),
                                     (signal.SIGKILL, self.kill_grace)):
                deadline = (cutoffs[0 if signum == signal.SIGTERM else 1] if cutoffs else
                            self.phase_cutoff(duration, 5 if signum == signal.SIGTERM else 3))
                sent = set()
                if signum == signal.SIGKILL and self.cgroup is not None:
                    try:
                        if self.capture_deadline is not None and self.cgroup.members():
                            self.escalated = True
                        self.cgroup.kill()
                    except Exception as exc:
                        errors.add(str(exc))  # still attempt every pidfd independently
                while True:
                    if cutoffs is not None:
                        cutoffs = self.begin_cleanup()
                        deadline = cutoffs[0 if signum == signal.SIGTERM else 1]
                    try:
                        self.refresh()
                    except Exception as exc:
                        errors.add(str(exc))
                    for handle in list(self.owned.values()):
                        try:
                            # Never signal a retired/exited process, even if a
                            # different process now occupies its numerical PID.
                            if (not handle.exited() and handle not in sent and
                                    not (self.outer_capture and signum == signal.SIGTERM and
                                         time.clock_gettime_ns(time.CLOCK_MONOTONIC) < deadline)):
                                if signum == signal.SIGKILL:
                                    self.escalated = True
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
                    if time.clock_gettime_ns(time.CLOCK_MONOTONIC) >= deadline:
                        break
                    time.sleep(.01)
            survivors = [h.identity for h in self._live(errors)]
            if survivors:
                errors.add(f"owned processes remain alive: {survivors}")
            if self.capture_deadline is not None and self.escalated:
                errors.add("capture cleanup required forced escalation")
            if self.capture_context is not None and self.capture_context.error is not None:
                errors.add(str(self.capture_context.error))
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

    def _release(self, value=None):
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
        if self.previous_subreaper is not None:
            try:
                if self.libc.prctl(36, self.previous_subreaper.value, 0, 0, 0):
                    self.errors.append("cannot restore subreaper state")
            except Exception as exc:
                self.errors.append(exc)
            finally:
                self.previous_subreaper = None
        if self.errors and self.capture_context is not None and self.capture_context.fd is not None:
            self.capture_context.begin(abort=True)
        if self.owns_context and self.capture_context is not None:
            try:
                self.capture_context.close()
            except Exception as exc:
                self.errors.append(exc)
            if (self.capture_context.aborted and _cancelled is None and
                    not isinstance(value, (SystemExit, KeyboardInterrupt)) and
                    not isinstance(self.lease_failure, (SystemExit, KeyboardInterrupt))):
                self.errors.append("capture aborted before positive root completion")
        if self.capture_lease is not None:
            failure = value if value is not None else self.lease_failure
            inherited = cleanup_failure(failure)
            errors = [*self.errors, *(inherited.errors if inherited else [])]
            if failure is not None and not isinstance(failure, (SystemExit, KeyboardInterrupt)):
                errors.append(f"capture root failed before final lease disposition: {failure}")
            disposition = CleanupError(errors) if errors else None
            if disposition is not None:
                self.errors = list(disposition.errors)
            if disposition is not None and failure is not None:
                retain_cleanup_failure(failure, disposition)
            lease, self.capture_lease = self.capture_lease, None
            try:
                lease.finish_capture(disposition)
            except BaseException as exc:
                # All root resources were independently visited; preserve first interruption.
                if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                    if value is None:
                        self.lease_failure = exc
                self.errors.append(exc)

    def _restore_handlers(self):
        """Restore every installed handler even if resource release itself failed."""
        for sig, handler in self.handlers.items():
            try:
                signal.signal(sig, handler)
            except Exception as exc:
                self.errors.append(exc)

    def __exit__(self, typ, value, traceback):
        global _cancelled, _cancelled_at
        with defer_cancellation(cleanup=True):
            if value is not None and self.capture_deadline is not None:
                self.begin_cleanup(abort=True)
            try:
                self.stop()
            except CleanupError:
                pass  # aggregate after independently releasing every handle
            except Exception as exc:
                self.errors.append(exc)
            finally:
                self._close_pipes()
                try:
                    self._release(value)
                except BaseException as exc:
                    self.errors.append(exc)
                    if isinstance(exc, (SystemExit, KeyboardInterrupt)) and self.lease_failure is None:
                        self.lease_failure = exc
                finally:
                    try:
                        self._restore_handlers()
                    finally:
                        _scopes.pop()
                        cancelled = _cancelled
                        if self.owns_cancellation:
                            _cancelled = None
                            _cancelled_at = None
        if self.capture_deadline is not None:
            interrupt = value if isinstance(value, (SystemExit, KeyboardInterrupt)) else (
                self.lease_failure if isinstance(self.lease_failure, (SystemExit, KeyboardInterrupt)) else cancelled)
            if interrupt is not None:
                inherited = cleanup_failure(value)
                errors = [*self.errors, *(inherited.errors if inherited else [])]
                if errors:
                    raise interrupt from retain_cleanup_failure(interrupt, CleanupError(errors))
                if interrupt is not value:
                    raise interrupt from value
                return False
        if self.errors:
            inherited = cleanup_failure(value)
            if inherited is not None:
                self.errors.extend(inherited.errors)
            if self.capture_deadline is not None and value is not None:
                retain_cleanup_failure(value, CleanupError(self.errors))
                return False
            raise CleanupError(self.errors) from value
        if cancelled is not None and typ is None and not _scopes:
            raise cancelled
