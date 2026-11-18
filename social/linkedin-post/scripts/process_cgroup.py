"""Optional delegated cgroup-v2 containment for one synchronous process scope."""
import os
from pathlib import Path
import uuid

ROOT = Path("/sys/fs/cgroup")
MAX_GROUPS = 4096


class OwnedCgroup:
    def __init__(self, path):
        self.path = path
        self.relative = "/" + str(path.relative_to(ROOT))

    @classmethod
    def create(cls, parent=None):
        try:
            if parent is None:
                entry = next(line[3:] for line in Path("/proc/self/cgroup").read_text().splitlines()
                             if line.startswith("0::"))
                parent = ROOT / entry.lstrip("/")
            path = parent / ("storyproof-" + uuid.uuid4().hex)
            path.mkdir()
            group = cls(path)
            if not os.access(path / "cgroup.procs", os.W_OK) \
                    or not os.access(path / "cgroup.kill", os.W_OK):
                path.rmdir()
                return None
            return group
        except (OSError, StopIteration):
            return None  # undelegated host: verified pidfd/subreaper fallback

    def attach_before_exec(self):
        # Popen invokes this only in this dedicated, synchronous CLI's forked
        # child, before exec can fork anything. No shell or PID assignment race.
        fd = os.open(self.path / "cgroup.procs", os.O_WRONLY)
        try:
            os.write(fd, b"0")
        finally:
            os.close(fd)

    def directories(self):
        def traversal_error(error):
            if isinstance(error, FileNotFoundError) and Path(error.filename) != self.path:
                return  # nested owner completed while this snapshot was walking
            raise error

        found = []
        for parent, _, _ in os.walk(self.path, onerror=traversal_error):
            found.append(Path(parent))
            if len(found) > MAX_GROUPS:
                raise RuntimeError("cgroup discovery limit exceeded")
        return found

    def members(self):
        pids = set()
        for path in self.directories():
            try:
                pids.update(map(int, (path / "cgroup.procs").read_text().split()))
            except FileNotFoundError:
                continue  # a nested owner removed its empty group
        return pids

    def contains(self, membership):
        return any(line == f"0::{self.relative}" or line.startswith(f"0::{self.relative}/")
                   for line in membership.decode("utf-8").splitlines())

    def kill(self):
        # Kernel atomically kills the entire contained tree, including concurrent
        # forks and setsid descendants. No numerical process/group IDs are used.
        (self.path / "cgroup.kill").write_text("1")

    def remove(self):
        errors = []
        for path in sorted(self.directories(), key=lambda p: len(p.parts), reverse=True):
            try:
                path.rmdir()
            except FileNotFoundError:
                pass
            except OSError as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("; ".join(errors))
