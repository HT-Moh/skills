"""Private Linux cleanup cell. Timing/abort only; never cleanup-success evidence."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import fcntl
import os
import re
import stat
import struct
import threading
import time
from typing import Literal

NS = 1_000_000_000
MAGIC = b"B2CLNUP\x01"
OMITTED = object()
SLOTS = {"supervisor": 32, "worker": 64, "node": 96}
ControlRole = Literal["supervisor", "worker", "node"]


def now_ns():
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC)


def unsigned(text, maximum):
    if not isinstance(text, str) or not re.fullmatch(r"0|[1-9][0-9]{0,19}", text):
        raise ValueError("invalid private cleanup integer")
    value = int(text)
    if value > maximum:
        raise ValueError("private cleanup integer exceeded")
    return value


def _duration(value, default):
    if value is OMITTED:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("invalid cleanup policy duration")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal(default) / NS:
            raise ValueError("invalid cleanup policy duration")
        return int(number * NS)
    except InvalidOperation as exc:
        raise ValueError("invalid cleanup policy duration") from exc


@dataclass(frozen=True)
class CleanupPolicy:
    term_ns: int = 10 * NS
    kill_ns: int = 2 * NS
    outer_ns: int = 2 * NS

    def __post_init__(self):
        for value, maximum in zip(self.values(), (10 * NS, 2 * NS, 2 * NS)):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("invalid cleanup policy")

    def values(self):
        return self.term_ns, self.kill_ns, self.outer_ns

    @classmethod
    def normalize(cls, *, grace=OMITTED, kill_grace=OMITTED, outer_grace=OMITTED):
        return cls(_duration(grace, 10 * NS), _duration(kill_grace, 2 * NS),
                   _duration(outer_grace, 2 * NS))

    @classmethod
    def parse(cls, fields):
        if len(fields) != 3:
            raise ValueError("invalid private cleanup policy")
        return cls(*(unsigned(v, m) for v, m in zip(fields, (10 * NS, 2 * NS, 2 * NS))))

    def require(self, grace=OMITTED, kill_grace=OMITTED, outer_grace=OMITTED):
        for supplied, expected, maximum in zip(
                (grace, kill_grace, outer_grace), self.values(), (10 * NS, 2 * NS, 2 * NS)):
            if supplied is not OMITTED and _duration(supplied, maximum) != expected:
                raise ValueError("nested cleanup policy changed")


class ControlError(RuntimeError):
    """Control evidence is unknown; existing lifecycle owner carries the disposition."""


class _Transfer:
    """One bounded positional I/O pass, sharing its EINTR allowance."""
    def __init__(self, fd, expiry):
        self.fd, self.expiry, self.interrupts = fd, expiry, 0

    def run(self, size, offset, data=None):
        result = bytearray()
        done = 0
        while done < size:
            try:
                part = (os.pread(self.fd, size - done, offset + done) if data is None else
                        os.pwrite(self.fd, data[done:], offset + done))
            except InterruptedError:
                self.interrupts += 1
                if self.interrupts > 8 or now_ns() >= self.expiry:
                    raise ControlError("cleanup control EINTR budget exhausted")
                continue
            count = len(part) if data is None else part
            if not 0 < count <= size - done:
                raise ControlError("cleanup control short/zero transfer")
            if data is None:
                result.extend(part)
            done += count
            if done < size and now_ns() >= self.expiry:
                raise ControlError("cleanup control transfer deadline expired")
        return bytes(result)

    def read(self, size, offset):
        return self.run(size, offset)

    def write(self, data, offset):
        self.run(len(data), offset, data)


class CleanupContext:
    """One owned FD per process, closed by its invocation-root ProcessScope.

    Creation/adoption transfers descriptor ownership to this context. Nested scopes
    borrow the object, not another descriptor; only the root closes it. ``fd=None``
    means retired, while typed errors and tightening-only bounds remain usable.
    """
    def __init__(self, fd: int, expiry: int, nonce: str, role: ControlRole,
                 policy: CleanupPolicy) -> None:
        if type(expiry) is not int or not 0 < expiry < 2**64:
            raise ValueError("invalid cleanup expiry")
        if not isinstance(nonce, str) or not re.fullmatch("[0-9a-f]{32}", nonce):
            raise ValueError("invalid cleanup nonce")
        if role not in SLOTS or not isinstance(policy, CleanupPolicy):
            raise ValueError("invalid cleanup role/policy")
        self.fd: int | None = fd
        self.expiry, self.nonce, self.role, self.policy = expiry, nonce, role, policy
        self.header = MAGIC + struct.pack("<Q", expiry) + bytes.fromhex(nonce)
        self.epoch: int | None = None
        self.aborted = False
        self.error: ControlError | None = None
        self._bounds: tuple[int, int, int] = (expiry - 5 * NS, expiry - 3 * NS, expiry)
        self._seen: list[tuple[int, int | None]] = [(0, None)] * 3
        self._lock = threading.RLock()
        self._publishing = False
        self._pending_abort = False

    @classmethod
    def create(cls, expiry: int, policy: CleanupPolicy) -> "CleanupContext":
        fd = os.memfd_create("b2-capture-cleanup", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            ctx = cls(fd, expiry, os.urandom(16).hex(), "supervisor", policy)
            os.ftruncate(fd, 128)
            _Transfer(fd, expiry).write(ctx.header + bytes(96), 0)
            fcntl.fcntl(fd, fcntl.F_ADD_SEALS,
                        fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
            ctx._admit()
            return ctx
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def inherit(cls, fd: int, expiry: int, nonce: str, role: ControlRole,
                policy: CleanupPolicy, *, lease_fd: int = -1) -> "CleanupContext":
        # Never close an unrelated stdio/lease alias on rejected private metadata.
        if type(fd) is not int or fd < 3 or fd == lease_fd:
            raise ValueError("cleanup fd aliases stdio/lease")
        try:
            if role != "worker":
                raise ValueError("private worker cleanup role required")
            os.set_inheritable(fd, False)
            ctx = cls(fd, expiry, nonce, role, policy)
            ctx._admit()
            return ctx
        except BaseException:
            os.close(fd)
            raise

    @classmethod
    def from_arguments(cls, expiry, fields, *, lease_fd=-1):
        if not fields:
            raise ValueError("private capture bootstrap fields required")
        fd = unsigned(fields[0], 2**31 - 1)
        if fd < 3 or fd == lease_fd:
            raise ValueError("cleanup fd aliases stdio/lease")
        try:
            if len(fields) != 6:
                raise ValueError("private capture bootstrap fields required")
            parsed_expiry = unsigned(expiry, 2**64 - 1)
            policy = CleanupPolicy.parse(fields[3:])
        except BaseException:
            os.close(fd)
            raise
        return cls.inherit(fd, parsed_expiry, fields[1], fields[2], policy, lease_fd=lease_fd)

    def _backing(self):
        info = os.fstat(self.fd)
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 0 or info.st_size != 128 or
                flags & os.O_ACCMODE != os.O_RDWR or flags & os.O_APPEND or
                os.readlink(f"/proc/self/fd/{self.fd}") != "/memfd:b2-capture-cleanup (deleted)"):
            raise ControlError("invalid cleanup control backing")

    def _admit(self):
        self._read()
        index = (SLOTS[self.role] - 32) // 32
        if self._seen[index][0]:
            raise ControlError("cleanup role already published")
        _Transfer(self.fd, self.expiry).write(b"\0", SLOTS[self.role] + 31)

    def _tighten(self, epoch):
        self.epoch = epoch if self.epoch is None else min(self.epoch, epoch)
        t = min(self.epoch + self.policy.term_ns, self.expiry - 5 * NS)
        k = min(t + self.policy.kill_ns, self.expiry - 3 * NS)
        o = min(k + self.policy.outer_ns, self.expiry)
        self._bounds = tuple(min(a, b) for a, b in zip(self._bounds, (t, k, o)))

    def _read(self):
        self._backing()
        io = _Transfer(self.fd, self.expiry)
        if io.read(32, 0) != self.header:
            raise ControlError("cleanup control binding changed")
        for index, base in enumerate((32, 64, 96)):
            first = io.read(1, base + 8)[0]
            payload = io.read(32, base)
            last = io.read(1, base + 8)[0]
            previous, epoch = self._seen[index]
            if (first not in (0, 1, 2) or last not in (0, 1, 2) or
                    first < previous or last < first or payload[9:] != bytes(23)):
                raise ControlError("invalid cleanup committed state")
            if first == 0:
                continue  # A concurrent commit is consumed next poll, never its partial E.
            value = struct.unpack_from("<Q", payload)[0]
            if (not max(1, self.expiry - 300 * NS) <= value <= now_ns() or
                    epoch is not None and value != epoch):
                raise ControlError("invalid cleanup committed epoch")
            self._seen[index] = last, value
            self._tighten(value)
            self.aborted |= last == 2

    def fail(self, error):
        if self.error is None:
            self.error = ControlError(f"cleanup control unknown: {error}")
            self._tighten(now_ns())
        self.aborted = True

    def observe(self):
        with self._lock:
            if self.error is None and not self._publishing:
                try:
                    self._read()
                except (OSError, ValueError, RuntimeError) as exc:
                    self.fail(exc)
        return self._bounds

    def bounds(self):
        return self.observe()

    def begin(self, *, abort=False, at=None):
        with self._lock:
            now = now_ns()
            epoch = now if at is None else at
            if type(epoch) is not int or not max(1, self.expiry - 300 * NS) <= epoch <= now:
                raise ValueError("invalid local cleanup epoch")
            # Local evidence exists before any fallible observation/publication. A
            # reentrant earlier receipt tightens fallback even while a write is active.
            self._tighten(epoch)
            self._pending_abort |= abort
            if self._publishing:
                return self._bounds
            self.observe()
            if self.error is not None:
                return self._bounds
            self._publishing = True
            try:
                base = SLOTS[self.role]
                index = (base - 32) // 32
                state, epoch = self._seen[index]
                io = _Transfer(self.fd, self.expiry)
                if state == 0:
                    epoch = self.epoch
                    io.write(struct.pack("<Q", epoch), base)
                    state = 2 if self._pending_abort else 1
                    io.write(bytes([state]), base + 8)
                    self._seen[index] = state, epoch
                    self._tighten(epoch)
                if state == 1 and self._pending_abort:
                    io.write(b"\x02", base + 8)
                    state = 2
                    self._seen[index] = state, epoch
                self.aborted |= state == 2
            except (OSError, ValueError, RuntimeError) as exc:
                self.fail(exc)
            finally:
                self._publishing = False
            return self._bounds

    def check(self):
        self.observe()
        if self.error is not None:
            raise self.error
        if self.aborted:
            raise ControlError("capture peer aborted")
        cutoff = min(self.expiry - 15 * NS, self._bounds[0])
        if now_ns() >= cutoff:
            self.begin(abort=True)
            raise ValueError("capture work deadline expired")
        return (cutoff - now_ns()) / NS

    def arguments(self, role):
        if role not in ("worker", "node") or self.fd is None:
            raise ValueError("invalid cleanup launch role")
        self.check()
        return [str(self.fd), self.nonce, role, *(str(n) for n in self.policy.values())]

    def close(self) -> None:
        if self.fd is None:
            return
        self.observe()
        fd, self.fd = self.fd, None
        try:
            os.close(fd)  # Linux close is not retried, including EINTR.
        except OSError as exc:
            self.fail(exc)
        if self.error is not None:
            raise self.error
