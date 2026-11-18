"""Real-filesystem regressions for bounded, descriptor-anchored runtime capture."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import sys
from types import SimpleNamespace

import pytest


SCRIPTS = Path(__file__).parents[1] / "social/linkedin-post/scripts"


@pytest.fixture
def runtime(monkeypatch):
    spec = importlib.util.spec_from_file_location("bounded_runtime", SCRIPTS / "exact_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Interpreter identification is outside these filesystem regressions.
    monkeypatch.setattr(module.shutil, "which", lambda name: "/trusted/node")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="v-test\n"))
    return module


def refused(runtime, root, match=None):
    with pytest.raises((ValueError, OSError), match=match):
        with runtime.snapshot(root):
            pytest.fail("unsafe runtime admitted")


@pytest.mark.parametrize("replacement", ["symlink", "directory"])
@pytest.mark.parametrize("ancestor", ["package", "root"])
def test_ancestor_replaced_at_file_open_never_reads_outside(runtime, tmp_path, monkeypatch,
                                                         replacement, ancestor):
    root = tmp_path / "root"
    package = root / "node_modules" / "pkg"
    package.mkdir(parents=True)
    (package / "driver.js").write_text("original")
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = (outside / "driver.js" if ancestor == "package"
                    else outside / "node_modules" / "pkg" / "driver.js")
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("outside")
    replaced = package if ancestor == "package" else root
    real_open = os.open
    opened = []
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path).name == "driver.js" and not swapped:
            swapped = True
            replaced.rename(replaced.with_name("old"))
            if replacement == "symlink":
                replaced.symlink_to(outside, target_is_directory=True)
            else:
                outside.rename(replaced)
        fd = real_open(path, flags, *args, **kwargs)
        if Path(path).name == "driver.js":
            opened.append(os.read(fd, 100))
            os.lseek(fd, 0, os.SEEK_SET)
        return fd

    monkeypatch.setattr(runtime.os, "open", swap_then_open)
    refused(runtime, root)
    assert swapped
    assert b"outside" not in opened


@pytest.mark.parametrize("replace_at_open", [False, True])
def test_fifo_is_rejected_without_blocking(runtime, tmp_path, monkeypatch, replace_at_open):
    source = tmp_path / "driver.js"
    if replace_at_open:
        source.write_text("regular at discovery")
        real_open = os.open

        def replace_with_fifo(path, flags, *args, **kwargs):
            if Path(path).name == source.name:
                source.unlink()
                os.mkfifo(source)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(runtime.os, "open", replace_with_fifo)
    else:
        os.mkfifo(source)

    def timeout(*_):
        raise AssertionError("FIFO open blocked before regular-file validation")

    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 1)
    try:
        refused(runtime, tmp_path, "regular")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("limit,match", [
    ("MAX_DIRECTORIES", "directory limit"),
    ("MAX_ENTRIES", "entry limit"),
    ("MAX_DEPTH", "depth limit"),
])
def test_empty_directory_discovery_is_bounded(runtime, tmp_path, monkeypatch, limit, match):
    directory = tmp_path / "node_modules"
    for _ in range(8):
        directory.mkdir()
        directory = directory / "nested"
    monkeypatch.setattr(runtime, limit, 3, raising=False)
    refused(runtime, tmp_path, match)


def test_ignored_entries_still_consume_discovery_budget(runtime, tmp_path, monkeypatch):
    for index in range(6):
        (tmp_path / f"ignored-{index}.txt").touch()
    monkeypatch.setattr(runtime, "MAX_ENTRIES", 3, raising=False)
    refused(runtime, tmp_path, "entry limit")


@pytest.mark.parametrize("error", [FileNotFoundError, PermissionError])
def test_directory_traversal_errors_surface(runtime, tmp_path, monkeypatch, error):
    dependency = tmp_path / "node_modules"
    dependency.mkdir()
    real_scandir = os.scandir
    inode = dependency.stat().st_ino

    def fail_scan(path):
        current = os.fstat(path) if isinstance(path, int) else os.stat(path)
        if current.st_ino == inode:
            raise error("dependency traversal failed")
        return real_scandir(path)

    monkeypatch.setattr(runtime.os, "scandir", fail_scan)
    refused(runtime, tmp_path, "traversal failed")


def test_discovered_file_disappearance_is_not_omitted(runtime, tmp_path, monkeypatch):
    source = tmp_path / "driver.js"
    source.write_text("original")
    real_open = os.open

    def remove_then_open(path, flags, *args, **kwargs):
        if Path(path).name == source.name:
            source.unlink()
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(runtime.os, "open", remove_then_open)
    refused(runtime, tmp_path)


@pytest.mark.parametrize("limit,value,match", [
    ("MAX_FILES", 1, "file limit"),
    ("MAX_BYTES", 5, "byte limit"),
])
def test_file_and_aggregate_byte_limits(runtime, tmp_path, monkeypatch, limit, value, match):
    (tmp_path / "first.js").write_bytes(b"123")
    (tmp_path / "second.py").write_bytes(b"456")
    monkeypatch.setattr(runtime, limit, value)
    refused(runtime, tmp_path, match)


def test_capture_deadline_covers_empty_directory_discovery(runtime, tmp_path, monkeypatch):
    dependency = tmp_path / "node_modules"
    dependency.mkdir()
    import time
    clock = [0]
    real_scandir = os.scandir
    inode = dependency.stat().st_ino

    def slow_scan(path):
        current = os.fstat(path) if isinstance(path, int) else os.stat(path)
        if current.st_ino == inode:
            clock[0] = 4
        return real_scandir(path)

    monkeypatch.setattr(runtime.os, "scandir", slow_scan)
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime, "MAX_CAPTURE_SECONDS", 3, raising=False)
    refused(runtime, tmp_path, "time limit")


def test_capture_deadline_checked_after_file_read(runtime, tmp_path, monkeypatch):
    (tmp_path / "driver.js").write_bytes(b"source")
    import time
    clock = [0]
    real_fdopen = os.fdopen

    class SlowReader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, size):
            data = self.handle.read(size)
            clock[0] = 4
            return data

    monkeypatch.setattr(runtime.os, "fdopen", lambda *a, **kw: SlowReader(real_fdopen(*a, **kw)))
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime, "MAX_CAPTURE_SECONDS", 3)
    refused(runtime, tmp_path, "time limit")


def test_digest_matches_copied_bytes_despite_later_source_mutation(runtime, tmp_path):
    (tmp_path / "driver.js").write_bytes(b"original")
    (tmp_path / "package.json").write_bytes(b"{}")
    (tmp_path / "ignored.json").write_bytes(b"ignored")
    (tmp_path / "ignored.txt").write_bytes(b"ignored")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "secret.js").write_bytes(b"ignored")
    package = tmp_path / "node_modules" / "pkg"
    package.mkdir(parents=True)
    (package / "data.bin").write_bytes(b"dependency")
    (package / ".bin").mkdir()
    (package / ".bin" / "ignored.js").touch()
    with runtime.snapshot(tmp_path) as (copied, digest):
        (tmp_path / "driver.js").write_bytes(b"changed")
        (package / "data.bin").write_bytes(b"changed dependency")
        paths = ["driver.js", "package.json", "node_modules/pkg/data.bin"]
        identity = {
            "python": sys.version, "node": "v-test",
            "files": [[path, hashlib.sha256((copied / path).read_bytes()).hexdigest()]
                      for path in paths],
        }
        assert digest == hashlib.sha256(json.dumps(
            identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert (copied / "driver.js").read_bytes() == b"original"
        assert (copied / "node_modules/pkg/data.bin").read_bytes() == b"dependency"
        assert sorted(str(path.relative_to(copied)) for path in copied.rglob("*")
                      if path.is_file()) == sorted(paths)
    assert not copied.exists()
    with runtime.snapshot(tmp_path) as (_, changed_digest):
        assert changed_digest != digest
