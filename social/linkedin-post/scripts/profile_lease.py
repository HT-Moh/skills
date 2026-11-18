"""Atomic shared profile lease and persistent fail-closed teardown quarantine."""
import fcntl
import json
import os
from pathlib import Path

from process_lifecycle import CleanupError, defer_cancellation

LEASE_NAME = ".linkedin-poster.lease"
ACTIVE = b'{"active":true}\n'
_inherited = None
_borrowed = False
_held_after_write_failure = []


def inherit_lease(profile, fd):
    global _inherited
    _inherited = (Path(profile).resolve(), fd)


class ProfileLease:
    def __init__(self, profile):
        self.profile = Path(profile).resolve()
        self.fd = None
        self.borrowed = False
        self.acquired = False

    def __enter__(self):
        global _borrowed
        self.profile.mkdir(parents=True, exist_ok=True)
        try:
            with defer_cancellation():
                if _inherited and self.profile == _inherited[0]:
                    if _borrowed:
                        raise ValueError("publisher profile already active")
                    self.fd = os.dup(_inherited[1])
                    held, named = os.fstat(self.fd), (self.profile / LEASE_NAME).stat()
                    if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
                        raise ValueError("profile lease changed")
                    self.borrowed = _borrowed = True
                    if os.pread(self.fd, 128, 0) != ACTIVE:
                        raise ValueError("publisher profile quarantined after incomplete teardown")
                else:
                    self.fd = os.open(self.profile / LEASE_NAME,
                                      os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                    try:
                        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError as exc:
                        raise ValueError("publisher profile already active") from exc
                    if os.pread(self.fd, 1, 0):
                        raise ValueError("publisher profile quarantined after incomplete teardown")
                    self.acquired = True
                    # Persist before any child starts. If the supervisor is
                    # SIGKILLed, or a later quarantine write fails, this existing
                    # marker still refuses future runs after every FD closes.
                    if os.pwrite(self.fd, ACTIVE, 0) != len(ACTIVE):
                        raise OSError("short active lease write")
                    os.fsync(self.fd)
                    # Also sync the lease's directory entry before any launch.
                    # This is not a guarantee against arbitrary storage failures.
                    directory = os.open(self.profile, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def quarantine(self, error):
        # The marker lives in the same never-unlinked inode as the flock. It
        # survives CLI exit and blocks every subsequent run/login, even without
        # SingletonLock. An operator must investigate before clearing its content.
        data = json.dumps({"quarantined": True, "reason": str(error)[:2000]}).encode("ascii")
        try:
            if os.pwrite(self.fd, data, 0) != len(data):
                raise OSError("short quarantine write")
            os.ftruncate(self.fd, len(data))
            os.fsync(self.fd)
        except OSError:
            # Retain the lock in this process if persistence fails. Report failure;
            # never silently unlock and admit a second browser.
            _held_after_write_failure.append(self.fd)
            self.fd = None
            raise

    def clean_singleton(self, identities):
        try:
            target = os.readlink(self.profile / "SingletonLock")
            pid = int(target.rsplit("-", 1)[1])
        except (OSError, ValueError, IndexError):
            return
        if pid not in {identity[0] for identity in identities} or Path(f"/proc/{pid}").exists():
            return
        errors = []
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "DevToolsActivePort"):
            try:
                (self.profile / name).unlink(missing_ok=True)
            except OSError as exc:
                errors.append(exc)
        if errors:
            raise CleanupError(errors)

    def __exit__(self, typ, value, traceback):
        global _borrowed
        with defer_cancellation(cleanup=True):
            try:
                if self.fd is not None and isinstance(value, CleanupError):
                    self.quarantine(value)
                elif self.fd is not None and self.acquired:
                    if os.pread(self.fd, 128, 0) != ACTIVE:
                        raise CleanupError(["profile quarantined by a nested owner"])
                    os.ftruncate(self.fd, 0)
                    os.fsync(self.fd)
            finally:
                if self.fd is not None:
                    os.close(self.fd)
                    self.fd = None
                if self.borrowed:
                    _borrowed = False
