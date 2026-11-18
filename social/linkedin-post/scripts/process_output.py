"""One bounded incremental collector for both Python workers and Node drivers."""
import os
import select
import selectors
import subprocess
import tempfile
import time
from collections.abc import Callable

from process_lifecycle import ProcessScope

MAX_OUTPUT = 1024 * 1024
MAX_FRAME = 65536


def read_initial(fd: int, *, timeout: float, limit: int = MAX_FRAME) -> bytes:
    """Read exactly one initial line without hiding pipelined input in buffered I/O."""
    deadline, body = time.monotonic() + timeout, bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise ValueError("initial frame timed out")
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


def collect(proc, scope, *, timeout, limit=MAX_OUTPUT):
    output, error = bytearray(), bytearray()
    total = 0
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        selector.register(proc.stdout, selectors.EVENT_READ)
        selector.register(proc.stderr, selectors.EVENT_READ)
        while selector.get_map() or proc.poll() is None:
            scope.refresh()
            remaining = deadline - time.monotonic()
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


def run_bounded(args, *, input, timeout, grace=10):
    # A regular temporary input file avoids blocking while a child fills stderr
    # without first reading stdin. Output always uses the incremental pipe reader.
    with tempfile.TemporaryFile() as stdin:
        stdin.write(input.encode("utf-8"))
        stdin.seek(0)
        with ProcessScope(grace=grace) as scope:
            proc = scope.spawn(args, stdin=stdin, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
            result = collect(proc, scope, timeout=timeout)
        return subprocess.CompletedProcess(result.args, result.returncode,
                                            result.stdout.decode("utf-8"),
                                            result.stderr.decode("utf-8"))


def relay(proc, scope, *, input: bytes, upstream: int, downstream: int,
          frame: Callable[[bytes], str], acknowledgment: Callable[[bytes], None],
          timeout: float, limit: int = MAX_OUTPUT) -> None:
    """Forward one exchange; no acknowledgment crosses until validated through EOF.

    Callbacks admit protocol identities. This owner enforces sequence and pipe budgets;
    exceptions escape to the caller's existing process/profile cleanup boundary.
    """
    if not input.endswith(b"\n") or len(input) > MAX_FRAME:
        raise ValueError("invalid initial relay frame")
    deadline = time.monotonic() + timeout
    child_input, output, incoming, child_buffer = bytearray(input), bytearray(), bytearray(), bytearray()
    phase, total, upstream_open = "preparing", 0, True
    stdout_open, stderr_open = True, True
    originals = {fd: os.get_blocking(fd) for fd in (upstream, downstream)}
    for fd in (*originals, proc.stdin.fileno(), proc.stdout.fileno(), proc.stderr.fileno()):
        os.set_blocking(fd, False)

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise ValueError("relay timed out")
        return value

    def child_stdout(chunk: bytes) -> None:
        nonlocal phase
        if phase == "terminal":
            raise ValueError("output after terminal")
        child_buffer.extend(chunk)
        if len(child_buffer) > MAX_FRAME:
            raise ValueError("relay frame limit exceeded")
        while b"\n" in child_buffer:
            raw, _, rest = child_buffer.partition(b"\n")
            child_buffer[:] = rest
            kind = frame(bytes(raw))
            remaining()
            if kind == "ready" and phase == "preparing" and not child_input:
                phase = "ready_pending"
            elif kind == "terminal" and phase in ("preparing", "acknowledged"):
                phase = "terminal"
            else:
                raise ValueError("invalid relay frame order")
            output.extend(raw + b"\n")
            if child_buffer:
                raise ValueError("premature trailing child output")

    try:
        with selectors.DefaultSelector() as selector:
            while True:
                scope.refresh()
                remaining()
                if not stdout_open and not stderr_open and proc.poll() is not None:
                    if proc.returncode or phase != "terminal" or child_buffer or output:
                        if output and not proc.returncode and phase == "terminal" and not child_buffer:
                            pass  # Flush the terminal even if the child has already exited.
                        else:
                            raise ValueError("relay exited without a complete terminal")
                    else:
                        return
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                if upstream_open and phase != "terminal":
                    selector.register(upstream, selectors.EVENT_READ, "upstream")
                if stdout_open:
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
                        chunk = os.read(key.fd, min(65536, limit - total + 1))
                        total += len(chunk)
                        if total > limit:
                            raise ValueError("process output limit exceeded")
                        if not chunk:
                            if name == "stdout":
                                stdout_open = False
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
    finally:
        for fd, blocking in originals.items():
            os.set_blocking(fd, blocking)


def run_stream(args, *, input: bytes, upstream: int, downstream: int,
               frame: Callable[[bytes], str], acknowledgment: Callable[[bytes], None],
               timeout: float, grace: float = 10) -> None:
    """Use the existing lifecycle owner for a bounded interactive driver."""
    with ProcessScope(grace=grace) as scope:
        proc = scope.spawn(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, start_new_session=True)
        relay(proc, scope, input=input, upstream=upstream, downstream=downstream,
              frame=frame, acknowledgment=acknowledgment, timeout=timeout)
