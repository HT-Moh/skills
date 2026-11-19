"""Final lease disposition faults while the original flock is still held."""
import errno
import fcntl
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_capture_control import SCRIPTS
import profile_lease as leases
from process_lifecycle import CleanupError, cleanup_failure


@pytest.mark.parametrize("fault", ["truncate", "fsync"])
@pytest.mark.parametrize("rollback_fault", ["none", "write", "short", "fsync"])
def test_clean_release_fault_rolls_back_under_same_lock(tmp_path, monkeypatch, fault, rollback_fault):
    lease = leases.ProfileLease(tmp_path / "profile")
    lease.__enter__()
    original_fd = lease.fd
    marker = lease.profile / leases.LEASE_NAME
    truncate, sync, write, close = os.ftruncate, os.fsync, os.pwrite, os.close
    error = OSError(errno.EIO, "clean release persistence fault")
    observed_lock = []
    closed = []
    def locked():
        other = os.open(marker, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            observed_lock.append(True)
        finally:
            close(other)
    def broken_truncate(fd, size):
        if fd == original_fd and size == 0 and fault == "truncate":
            locked()
            raise error
        return truncate(fd, size)
    def broken_sync(fd):
        if fd == original_fd:
            data = os.pread(fd, 2000, 0)
            if not data and fault == "fsync":
                locked()
                raise error
            if b'"quarantined"' in data and rollback_fault == "fsync":
                locked()
                raise OSError(errno.EIO, "quarantine fsync fault")
        return sync(fd)
    def broken_write(fd, data, offset):
        if fd == original_fd and b'"quarantined"' in data:
            locked()
            if rollback_fault == "write":
                raise OSError(errno.EIO, "quarantine write fault")
            if rollback_fault == "short":
                return write(fd, data[:1], offset)
        return write(fd, data, offset)
    def record_close(fd):
        if fd == original_fd:
            closed.append(fd)
        return close(fd)
    monkeypatch.setattr(os, "ftruncate", broken_truncate)
    monkeypatch.setattr(os, "fsync", broken_sync)
    monkeypatch.setattr(os, "pwrite", broken_write)
    monkeypatch.setattr(os, "close", record_close)
    try:
        with pytest.raises(OSError) as caught:
            lease.__exit__(None, None, None)
        assert caught.value is error
        assert cleanup_failure(error) is not None
        assert observed_lock
        assert marker.read_bytes(), "failed rollback must not abandon the empty clean marker"
        if rollback_fault == "none":
            assert b'"quarantined": true' in marker.read_bytes()
            assert closed == [original_fd]
        else:
            assert original_fd in leases._held_after_write_failure
            assert closed == []
            locked()
        # A separate acquisition cannot succeed, whether retained lock or marker refuses it.
        with pytest.raises(ValueError, match="active|quarantined"):
            with leases.ProfileLease(lease.profile):
                pass
    finally:
        if original_fd in leases._held_after_write_failure:
            leases._held_after_write_failure.remove(original_fd)
            close(original_fd)


@pytest.mark.parametrize("borrowed", [False, True])
@pytest.mark.parametrize("fault", ["none", "write", "short", "fsync"])
def test_unknown_cleanup_quarantine_matrix_preserves_borrowed_lock(tmp_path, monkeypatch, borrowed, fault):
    parent = leases.ProfileLease(tmp_path / "profile")
    parent.__enter__()
    if borrowed:
        monkeypatch.setattr(leases, "_inherited", (parent.profile, parent.fd))
        lease = leases.ProfileLease(parent.profile)
        lease.__enter__()
    else:
        lease = parent
    fd, parent_fd = lease.fd, parent.fd
    write, sync, close, flock = os.pwrite, os.fsync, os.close, fcntl.flock
    unlocks = []
    def broken_write(target, data, offset):
        if target == fd:
            if fault == "write":
                raise OSError(errno.EIO, "quarantine write fault")
            if fault == "short":
                return write(target, data[:1], offset)
        return write(target, data, offset)
    def broken_sync(target):
        if target == fd and fault == "fsync":
            raise OSError(errno.EIO, "quarantine fsync fault")
        return sync(target)
    def record_flock(target, operation):
        if operation == fcntl.LOCK_UN:
            unlocks.append(target)
        return flock(target, operation)
    monkeypatch.setattr(os, "pwrite", broken_write)
    monkeypatch.setattr(os, "fsync", broken_sync)
    monkeypatch.setattr(fcntl, "flock", record_flock)
    failure = CleanupError(["owned cleanup unknown"])
    try:
        if fault == "none":
            lease.__exit__(CleanupError, failure, None)
        else:
            with pytest.raises(OSError):
                lease.__exit__(CleanupError, failure, None)
        assert not unlocks
        assert (parent.profile / leases.LEASE_NAME).read_bytes()
        if borrowed:
            # Separate open must remain excluded by the parent's original flock.
            monkeypatch.setattr(leases, "_inherited", None)
            with pytest.raises(ValueError, match="active"):
                with leases.ProfileLease(parent.profile / ".." / "profile"):
                    pass
            if fault in ("write", "short"):
                # Failed worker persistence may leave ACTIVE unchanged. Its failed
                # exit carries typed unknown to the supervisor, which must not clear it.
                parent.__exit__(CleanupError, failure, None)
            else:
                with pytest.raises((CleanupError, OSError)):
                    parent.__exit__(None, None, None)
            assert (parent.profile / leases.LEASE_NAME).read_bytes()
    finally:
        for held in {fd, parent_fd}:
            if held in leases._held_after_write_failure:
                leases._held_after_write_failure.remove(held)
                close(held)
        if parent.fd is not None:
            close(parent.fd)
            parent.fd = None


def test_failed_clean_rollback_refuses_reacquisition_after_process_exit(tmp_path):
    source = """
import errno,os,sys
from profile_lease import ProfileLease
with ProfileLease(sys.argv[1]):
 real_sync,real_write=os.fsync,os.pwrite
 def sync(fd):
  if os.fstat(fd).st_size==0:raise OSError(errno.EIO,'empty fsync fault')
  return real_sync(fd)
 def write(fd,data,offset):
  if b'quarantined' in data:raise OSError(errno.EIO,'quarantine write fault')
  return real_write(fd,data,offset)
 os.fsync,os.pwrite=sync,write
"""
    profile = tmp_path / "profile"
    result = subprocess.run([sys.executable, "-c", source, str(profile)],
        env={**os.environ, "PYTHONPATH": str(SCRIPTS)}, capture_output=True, timeout=3)
    assert result.returncode != 0
    assert (profile / leases.LEASE_NAME).read_bytes()
    with pytest.raises(ValueError, match="quarantined"):
        with leases.ProfileLease(profile):
            pass


@pytest.mark.parametrize("borrowed", [False, True])
def test_lease_close_error_is_typed_never_retried_and_preserves_primary(tmp_path, monkeypatch, borrowed):
    parent = leases.ProfileLease(tmp_path / "profile")
    parent.__enter__()
    if borrowed:
        monkeypatch.setattr(leases, "_inherited", (parent.profile, parent.fd))
        lease = leases.ProfileLease(parent.profile)
        lease.__enter__()
    else:
        lease = parent
    fd = lease.fd
    close, sync = os.close, os.fsync
    calls = []
    primary = OSError(errno.EIO, "primary clean fsync fault")
    def fail_sync(target):
        if target == fd and os.fstat(target).st_size == 0:
            raise primary
        return sync(target)
    def fail_close(target):
        if target == fd:
            calls.append(target)
            close(target)  # Model Linux releasing the fd even when close reports EIO.
            raise OSError(errno.EIO, "descriptor close fault")
        return close(target)
    monkeypatch.setattr(os, "fsync", fail_sync)
    monkeypatch.setattr(os, "close", fail_close)
    try:
        with pytest.raises(OSError) as caught:
            lease.__exit__(None, None, None)
        if not borrowed:
            assert caught.value is primary
            assert b'"quarantined": true' in (parent.profile / leases.LEASE_NAME).read_bytes()
        else:
            assert (parent.profile / leases.LEASE_NAME).read_bytes() == leases.ACTIVE
        assert "descriptor close fault" in str(cleanup_failure(caught.value))
        assert calls == [fd] and lease.fd is None
        lease.__exit__(None, None, None)
        assert calls == [fd]
    finally:
        if parent.fd is not None:
            close(parent.fd)
            parent.fd = None


def test_first_signal_during_empty_fsync_preserves_interrupt_and_quarantines(tmp_path, monkeypatch):
    import signal
    import time
    from exact_capture_clock import Deadline
    from process_lifecycle import ProcessScope
    sync = os.fsync
    fired = []
    def fail_sync(fd):
        if os.readlink("/proc/self/fd/" + str(fd)).endswith("/" + leases.LEASE_NAME) and os.fstat(fd).st_size == 0:
            os.kill(os.getpid(), signal.SIGTERM)
            fired.append(True)
            raise OSError(errno.EIO, "cancelled clean fsync")
        return sync(fd)
    monkeypatch.setattr(os, "fsync", fail_sync)
    with pytest.raises(SystemExit) as caught:
        with ProcessScope(use_cgroup=False, capture_deadline=Deadline(str(time.monotonic_ns()+60_000_000_000))):
            with leases.ProfileLease(tmp_path / "profile"):
                pass
    assert fired == [True] and caught.value.code == 143
    assert "cancelled clean fsync" in str(cleanup_failure(caught.value))
    with pytest.raises(ValueError, match="quarantined"):
        with leases.ProfileLease(tmp_path / "profile"):
            pass
