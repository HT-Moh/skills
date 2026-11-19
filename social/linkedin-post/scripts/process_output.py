"""One bounded incremental collector for both Python workers and Node drivers."""
import os
import select
import selectors
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from process_lifecycle import (
    CleanupError, ProcessScope, defer_cancellation, retain_cleanup_failure,
    current_scope, cancellation_checkpoint,
)
from capture_control import OMITTED

MAX_OUTPUT = 1024 * 1024
MAX_FRAME = 65536


def read_initial(fd: int, *, timeout: float, limit: int = MAX_FRAME) -> bytes:
    """Read exactly one initial line without hiding pipelined input in buffered I/O."""
    deadline, body = time.monotonic() + timeout, bytearray()
    while True:
        cancellation_checkpoint()
        remaining = deadline - time.monotonic()
        try:
            scope = current_scope()
        except RuntimeError:
            scope = None
        if scope is not None and scope.capture_context is not None:
            remaining = min(remaining, scope.check_work())
        if remaining <= 0:
            raise ValueError("initial frame timed out")
        if not select.select([fd], [], [], min(remaining, .05))[0]:
            continue
        chunk = os.read(fd, limit - len(body) + 1)
        if not chunk:
            raise ValueError("initial frame missing newline")
        body.extend(chunk)
        if len(body) > limit:
            raise ValueError("initial frame limit exceeded")
        if b"\n" in body:
            if body.count(b"\n") != 1 or not body.endswith(b"\n"):
                raise ValueError("request and acknowledgment pipelined")
            return bytes(body)


def collect(proc, scope, *, timeout, limit=MAX_OUTPUT, capture_deadline=None):
    output, error = bytearray(), bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        selector.register(proc.stderr, selectors.EVENT_READ)
        while selector.get_map() or proc.poll() is None:
            scope.check_work()
            scope.refresh()
            remaining = deadline - time.monotonic()
            if capture_deadline is not None:
                remaining = min(remaining, capture_deadline.remaining())
            if remaining <= 0:
                raise ValueError("preview process timed out")
            for key, _ in selector.select(min(remaining, .05)):
                chunk = os.read(key.fd, min(65536, limit - total + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > limit:
                    raise ValueError("process output limit exceeded")
                (output if key.fileobj is proc.stdout else error).extend(chunk)
    return subprocess.CompletedProcess(proc.args, proc.returncode, bytes(output), bytes(error))


def run_bounded(args, *, input, timeout, grace=OMITTED, capture_deadline=None, auxiliary=False):
    # A regular temporary input file avoids blocking while a child fills stderr
    # without first reading stdin. Output always uses the incremental pipe reader.
    with ProcessScope(grace=grace, capture_deadline=capture_deadline, auxiliary=auxiliary) as scope, \
            tempfile.TemporaryFile() as stdin:
        stdin.write(input.encode("utf-8"))
        stdin.seek(0)
        proc = scope.spawn(args, stdin=stdin, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, start_new_session=True)
        result = collect(proc, scope, timeout=timeout, capture_deadline=capture_deadline)
        if capture_deadline is not None and result.returncode:
            scope.begin_cleanup(abort=True)
        return subprocess.CompletedProcess(result.args, result.returncode,
                                            result.stdout.decode("utf-8"),
                                            result.stderr.decode("utf-8"))


@dataclass(frozen=True)
class RelayCompletion:
    """Actual child observations only; enclosing owners attest cleanup by successful exit."""
    stdout_eof: bool
    stderr_eof: bool
    exit_code: int | None
    stdout_bytes: int
    stderr_bytes: int
    frames: int
    peak_pending_bytes: int


class RelayFailure(ValueError):
    """Bounded failure evidence, before enclosing resource owners finish cleanup."""

    def __init__(self, original: BaseException, observations: RelayCompletion, stderr_tail: bytes):
        self.original_failure = original
        self.observations = observations
        self.stderr_tail = stderr_tail
        detail = stderr_tail.decode("utf-8", errors="replace")
        super().__init__(f"{original}: {detail}" if detail else str(original))


def relay(proc, scope, *, input: bytes, upstream: int, downstream: int,
          frame: Callable[[bytes], str], acknowledgment: Callable[[bytes], None],
          timeout: float, limit: int = MAX_OUTPUT, capture_deadline=None) -> RelayCompletion | None:
    """Forward one exchange; no acknowledgment crosses until validated through EOF.

    Callbacks admit protocol identities. This owner enforces sequence and pipe budgets;
    exceptions escape to the caller's existing process/profile cleanup boundary.
    """
    if not input.endswith(b"\n") or len(input) > MAX_FRAME:
        raise ValueError("invalid initial relay frame")
    capture = capture_deadline is not None
    if capture:
        from exact_capture import LIMITS, decode_capture
        decode_capture(input)
        limit = LIMITS["combined_output_bytes"]
    deadline = time.monotonic() + timeout
    child_input, output, incoming, child_buffer = bytearray(input), bytearray(), bytearray(), bytearray()
    phase, total, upstream_open = "preparing", 0, True
    stdout_open, stderr_open = True, True
    stdout_bytes = stderr_bytes = frames = chunks = peak_pending = 0
    stderr_tail = bytearray()
    originals = {fd: os.get_blocking(fd) for fd in (upstream, downstream)}
    for fd in (*originals, proc.stdin.fileno(), proc.stdout.fileno(), proc.stderr.fileno()):
        os.set_blocking(fd, False)

    def remaining() -> float:
        if capture:
            # Once terminal is forwarded, observe the child's cleanup through the
            # TERM cutoff, leaving the shared KILL/reap interval to ProcessScope.
            cancellation_checkpoint()
            if phase == "terminal" and not output:
                cutoff = scope.begin_cleanup()[0]
                if scope.capture_context.aborted:
                    raise CleanupError(["capture peer aborted during terminal cleanup"])
                left = (cutoff - time.clock_gettime_ns(time.CLOCK_MONOTONIC)) / 1e9
                if left <= 0:
                    raise ValueError("capture cleanup deadline expired")
                return left
            return min(capture_deadline.remaining(), scope.check_work())
        value = deadline - time.monotonic()
        if value <= 0:
            raise ValueError("relay timed out")
        return value

    def child_stdout(chunk: bytes) -> None:
        nonlocal phase, frames, chunks, peak_pending
        if phase == "terminal":
            raise ValueError("output after terminal")
        child_buffer.extend(chunk)
        if not capture and len(child_buffer) > MAX_FRAME:
            raise ValueError("relay frame limit exceeded")
        while b"\n" in child_buffer:
            raw, _, rest = child_buffer.partition(b"\n")
            child_buffer[:] = rest
            if capture:
                decode_capture(bytes(raw) + b"\n")
            kind = frame(bytes(raw) + (b"\n" if capture else b""))
            remaining()
            if kind == "ready" and phase == "preparing" and not child_input:
                phase = "ready_pending"
            elif kind == "chunk" and capture and phase == "acknowledged" and chunks < 32:
                chunks += 1
            elif kind == "declaration" and capture and phase == "acknowledged":
                phase = "declared"
            elif kind == "terminal" and phase in (("preparing", "declared") if capture
                                                   else ("preparing", "acknowledged")):
                phase = "terminal"
            else:
                raise ValueError("invalid relay frame order")
            output.extend(raw + b"\n")
            frames += 1
            peak_pending = max(peak_pending, len(output) + len(child_buffer))
            if capture and frames > LIMITS["stdout_frames"]:
                raise ValueError("capture frame count exceeded")
            if child_buffer and (not capture or phase in ("ready_pending", "terminal")):
                raise ValueError("premature trailing child output")
            if capture:
                break  # Forward exactly one frame before admitting the next.
        if capture and not output and len(child_buffer) >= MAX_FRAME:
            raise ValueError("relay frame limit exceeded")

    def observe_failed_cleanup():
        """Freeze all protocol activity; boundedly discard output while owners unwind.

        Closing pre-ack stdin sends invalid EOF to the child, never an acknowledgment.
        A partially written ack is left open: EOF there could authorize an effect.
        No callback, downstream write or further stdin write is allowed in this mode.
        """
        nonlocal stdout_open, stderr_open, stdout_bytes, stderr_bytes, total
        scope.begin_cleanup(abort=True)
        output.clear()
        child_buffer.clear()
        child_input.clear()
        incoming.clear()
        if phase in ("preparing", "ready_pending", "ready") and not proc.stdin.closed:
            proc.stdin.close()
        with selectors.DefaultSelector() as observer:
            while True:
                cutoff = scope.begin_cleanup()[0]
                if not stdout_open and not stderr_open and proc.poll() is not None:
                    return
                left = (cutoff - time.clock_gettime_ns(time.CLOCK_MONOTONIC)) / 1_000_000_000
                if left <= 0:
                    return
                scope.refresh()
                for key in list(observer.get_map().values()):
                    observer.unregister(key.fileobj)
                # Once a byte ceiling is exceeded, stop reading that resource.
                # Waiting for the owner remains bounded even if its pipe blocks.
                if total <= limit:
                    if stdout_open:
                        observer.register(proc.stdout, selectors.EVENT_READ, "stdout")
                    if stderr_open and stderr_bytes <= LIMITS["stderr_bytes"]:
                        observer.register(proc.stderr, selectors.EVENT_READ, "stderr")
                for key, _ in observer.select(min(left, .05)):
                    budget = limit - total + 1
                    if key.data == "stderr":
                        budget = min(budget, LIMITS["stderr_bytes"] - stderr_bytes + 1)
                    if budget <= 0:
                        continue
                    chunk = os.read(key.fd, min(8192, budget))
                    total += len(chunk)
                    if key.data == "stdout":
                        stdout_bytes += len(chunk)
                        if not chunk:
                            stdout_open = False
                    else:
                        stderr_bytes += len(chunk)
                        stderr_tail[:] = (stderr_tail + chunk)[-1024:]
                        if not chunk:
                            stderr_open = False

    try:
        with selectors.DefaultSelector() as selector:
            while True:
                scope.refresh()
                remaining()
                if capture and child_buffer and not output:
                    child_stdout(b"")
                if not stdout_open and not stderr_open and proc.poll() is not None:
                    if proc.returncode or phase != "terminal" or child_buffer or output:
                        if output and not proc.returncode and phase == "terminal" and not child_buffer:
                            pass  # Flush the terminal even if the child has already exited.
                        else:
                            raise ValueError("relay exited without a complete terminal")
                    else:
                        return (RelayCompletion(True, True, proc.returncode, stdout_bytes, stderr_bytes,
                                                frames, peak_pending) if capture else None)
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                if upstream_open and phase != "terminal":
                    selector.register(upstream, selectors.EVENT_READ, "upstream")
                if stdout_open and (not capture or not output):
                    selector.register(proc.stdout, selectors.EVENT_READ, "stdout")
                if stderr_open:
                    selector.register(proc.stderr, selectors.EVENT_READ, "stderr")
                if child_input:
                    selector.register(proc.stdin, selectors.EVENT_WRITE, "stdin")
                if output:
                    selector.register(downstream, selectors.EVENT_WRITE, "downstream")
                events = selector.select(min(remaining(), .05))
                # Read upstream first: input already present before ready is flushed is early.
                priority = {"upstream": 0, "stdout": 1, "stderr": 2, "downstream": 3, "stdin": 4}
                for key, _ in sorted(events, key=lambda event: priority[event[0].data]):
                    remaining()
                    name = key.data
                    if name == "upstream":
                        chunk = os.read(upstream, MAX_FRAME - len(incoming) + 1)
                        if phase != "ready":
                            raise ValueError("acknowledgment before ready")
                        if chunk:
                            incoming.extend(chunk)
                            if len(incoming) > MAX_FRAME:
                                raise ValueError("acknowledgment limit exceeded")
                        else:
                            upstream_open = False
                            acknowledgment(bytes(incoming))
                            remaining()
                            if not incoming.endswith(b"\n") or incoming.count(b"\n") != 1:
                                raise ValueError("one acknowledgment frame and EOF required")
                            child_input.extend(incoming)
                            phase = "ack_pending"
                    elif name in ("stdout", "stderr"):
                        chunk = os.read(key.fd, min(8192 if capture else 65536, limit - total + 1))
                        total += len(chunk)
                        if name == "stdout":
                            stdout_bytes += len(chunk)
                        else:
                            stderr_bytes += len(chunk)
                            if capture:
                                stderr_tail[:] = (stderr_tail + chunk)[-1024:]
                            if capture and stderr_bytes > LIMITS["stderr_bytes"]:
                                raise ValueError("capture stderr limit exceeded")
                        if total > limit:
                            raise ValueError("process output limit exceeded")
                        if not chunk:
                            if name == "stdout":
                                stdout_open = False
                                if capture and (phase != "terminal" or child_buffer):
                                    raise ValueError("relay stdout EOF before a complete terminal")
                            else:
                                stderr_open = False
                        elif name == "stdout":
                            child_stdout(chunk)
                    elif name == "downstream":
                        output[:os.write(downstream, output)] = b""
                        if not output and phase == "ready_pending":
                            phase = "ready"
                    elif name == "stdin":
                        if phase == "ack_pending":
                            # Reject buffered/already-readable stdout before every ack write.
                            if child_buffer or select.select([proc.stdout], [], [], 0)[0]:
                                raise ValueError("premature child output before acknowledgment")
                        remaining()
                        child_input[:os.write(proc.stdin.fileno(), child_input)] = b""
                        if not child_input and phase == "ack_pending":
                            proc.stdin.close()
                            phase = "acknowledged"
    except BaseException as error:
        if capture:
            # No protocol failure, nonzero exit or local pipe close proves entered
            # child scopes discharged. Carry uncertainty through existing leases.
            unknown = CleanupError(["capture child teardown unknown after relay failure"])
            with defer_cancellation(cleanup=True):
                try:
                    scope.begin_cleanup(abort=True)
                    observe_failed_cleanup()
                except Exception as cleanup_error:
                    unknown = CleanupError([*unknown.errors, cleanup_error])
            observations = RelayCompletion(not stdout_open, not stderr_open, proc.poll(),
                                           stdout_bytes, stderr_bytes, frames, peak_pending)
            failure = RelayFailure(error, observations, bytes(stderr_tail))
            retain_cleanup_failure(failure, unknown)
            if isinstance(error, (SystemExit, KeyboardInterrupt)):
                retain_cleanup_failure(error, unknown)
                raise error from failure
            raise failure from error
        raise
    finally:
        for fd, blocking in originals.items():
            os.set_blocking(fd, blocking)


def run_stream(args, *, input: bytes, upstream: int, downstream: int,
               frame: Callable[[bytes], str], acknowledgment: Callable[[bytes], None],
               timeout: float, grace=OMITTED, capture_deadline=None,
               capture_node=False) -> RelayCompletion | None:
    """Use the existing lifecycle owner for a bounded interactive driver."""
    if capture_deadline is not None:
        from exact_capture import decode_capture
        if not input.endswith(b"\n") or len(input) > MAX_FRAME:
            raise ValueError("invalid initial relay frame")
        decode_capture(input)
        capture_deadline.remaining()
    with ProcessScope(grace=grace, capture_deadline=capture_deadline) as scope:
        passed = ()
        if capture_node:
            if scope.capture_context is None:
                raise ValueError("capture Node launch requires private control")
            fields = scope.capture_context.arguments("node")
            args = [*args, fields[0], str(scope.capture_context.expiry), *fields[1:]]
            passed = (scope.capture_context.fd,)
        proc = scope.spawn(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, start_new_session=True,
                           close_fds=True, pass_fds=passed)
        result = relay(proc, scope, input=input, upstream=upstream, downstream=downstream,
                       frame=frame, acknowledgment=acknowledgment, timeout=timeout,
                       capture_deadline=capture_deadline)
    return result
