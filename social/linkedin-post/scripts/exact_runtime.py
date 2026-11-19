"""Capture executed publisher sources and dependencies, not mutable configured paths."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time

MAX_FILES = 15000
MAX_BYTES = 256 * 1024 * 1024
MAX_DIRECTORIES = 4096
MAX_ENTRIES = 50000
MAX_DEPTH = 64
MAX_CAPTURE_SECONDS = 30
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _same_object(before, after):
    return (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode)) == (
        after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode))


class _Capture:
    """Keep directory capabilities alive until the final namespace check."""

    def __init__(self, stack, deadline, capture_deadline=None):
        self.stack = stack
        self.deadline = deadline
        self.capture_deadline = capture_deadline
        self.directories = 0
        self.entries = 0
        self.files = 0
        self.namespace = []

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if self.capture_deadline is not None:
            remaining = min(remaining, self.capture_deadline.remaining())
        if remaining <= 0:
            raise ValueError("runtime capture time limit exceeded")
        return remaining

    def directory(self, name, parent=None, expected=None):
        self.remaining()
        fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
        self.stack.callback(os.close, fd)
        actual = os.fstat(fd)
        if expected is not None and not _same_object(expected, actual):
            raise ValueError("runtime namespace changed")
        if parent is not None:
            self.namespace.append((parent, name, actual))
        self.remaining()
        return fd

    def root(self, root):
        # Do not resolve symlinks, even in the configured root's ancestors.
        parts = Path(root).absolute().parts
        if len(parts) > 256 or ".." in parts:
            raise ValueError("runtime root path unsupported")
        fd = self.directory(parts[0])
        for name in parts[1:]:
            expected = os.stat(name, dir_fd=fd, follow_symlinks=False)
            fd = self.directory(name, fd, expected)
        return fd

    def validate_namespace(self):
        for parent, name, expected in self.namespace:
            self.remaining()
            actual = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not _same_object(expected, actual):
                raise ValueError("runtime namespace changed")
        self.remaining()


def _paths(capture, parent, relative=Path("."), depth=0):
    capture.remaining()
    if depth > MAX_DEPTH:
        raise ValueError("runtime depth limit exceeded")
    capture.directories += 1
    if capture.directories > MAX_DIRECTORIES:
        raise ValueError("runtime directory limit exceeded")
    directories, files = [], []
    # scandir(fd) never resolves a mutable ancestor path. Errors propagate.
    with os.scandir(parent) as entries:
        for entry in entries:
            capture.remaining()
            capture.entries += 1
            if capture.entries > MAX_ENTRIES:
                raise ValueError("runtime entry limit exceeded")
            name = entry.name
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            directory_selected = (
                name == "node_modules" if relative == Path(".")
                else name not in {".bin", "__pycache__"}
            )
            file_selected = relative != Path(".") or (
                Path(name).suffix in {".py", ".js"}
                or name in {"package.json", "package-lock.json"}
            )
            if stat.S_ISLNK(info.st_mode) and (directory_selected or file_selected):
                raise ValueError("runtime symlink unsupported")
            if stat.S_ISDIR(info.st_mode):
                if directory_selected:
                    directories.append((name, info))
            elif file_selected:
                capture.files += 1
                if capture.files > MAX_FILES:
                    raise ValueError("runtime file limit exceeded")
                files.append((name, info))
    for name, info in sorted(files):
        capture.remaining()
        yield parent, name, relative / name, info
    for name, info in sorted(directories):
        capture.remaining()
        # Check before opening, not only after allocating another descriptor.
        if depth + 1 > MAX_DEPTH:
            raise ValueError("runtime depth limit exceeded")
        if capture.directories >= MAX_DIRECTORIES:
            raise ValueError("runtime directory limit exceeded")
        child = capture.directory(name, parent, info)
        yield from _paths(capture, child, relative / name, depth + 1)


@contextmanager
def snapshot(root: Path, *, capture_deadline=None):
    """Copy and hash the same bytes through pinned, no-follow directory handles.

    Python/Node binaries, stdlib, environment and OS remain trusted; version strings
    identify interpreters but do not attest their binaries. This is not an atomic
    filesystem snapshot: in-place source writes can change bytes during a read.
    Namespace checks reject observed replacements; restored transient renames are
    not a filesystem event log. The deadline is cooperative between syscalls, not
    preemption of a stalled filesystem/kernel call.
    """
    deadline = time.monotonic() + MAX_CAPTURE_SECONDS
    if capture_deadline is not None:
        deadline = min(deadline, time.monotonic() + capture_deadline.remaining())
    node = shutil.which("node")
    if not node:
        raise ValueError("node unavailable")
    with tempfile.TemporaryDirectory(prefix="linkedin-exact-runtime-") as temporary:
        destination = Path(temporary)
        with ExitStack() as stack:
            capture = _Capture(stack, deadline, capture_deadline)
            if capture_deadline is None:
                version = subprocess.run(
                    [node, "--version"], capture_output=True, text=True, check=True,
                    timeout=min(10, capture.remaining()),
                ).stdout.strip()
            else:
                from process_output import run_bounded
                result = run_bounded([node, "--version"], input="", timeout=min(10, capture.remaining()),
                                     capture_deadline=capture_deadline, auxiliary=True)
                if result.returncode:
                    raise ValueError("runtime version probe failed")
                version = result.stdout.strip()
            identity = {"python": sys.version, "node": version, "files": []}
            root_fd = capture.root(root)
            total = 0
            for parent, name, relative, expected in _paths(capture, root_fd):
                capture.remaining()
                if not stat.S_ISREG(expected.st_mode):
                    raise ValueError("runtime requires regular files")
                # O_NONBLOCK also handles a regular file replaced by a FIFO after stat.
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                             | os.O_CLOEXEC, dir_fd=parent)
                with os.fdopen(fd, "rb") as handle:
                    actual = os.fstat(handle.fileno())
                    if not stat.S_ISREG(actual.st_mode):
                        raise ValueError("runtime requires regular files")
                    if not _same_object(expected, actual):
                        raise ValueError("runtime namespace changed")
                    capture.namespace.append((parent, name, actual))
                    target = destination / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    hasher = hashlib.sha256()
                    with target.open("wb") as output:
                        while True:
                            capture.remaining()
                            data = handle.read(min(1024 * 1024, MAX_BYTES - total + 1))
                            capture.remaining()
                            if not data:
                                break
                            total += len(data)
                            if total > MAX_BYTES:
                                raise ValueError("runtime byte limit exceeded")
                            output.write(data)
                            hasher.update(data)
                    identity["files"].append([relative.as_posix(), hasher.hexdigest()])
            capture.validate_namespace()
            digest = hashlib.sha256(json.dumps(
                identity, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            capture.remaining()
        yield destination, digest
