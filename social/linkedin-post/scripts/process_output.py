"""One bounded incremental collector for both Python workers and Node drivers."""
import os
import selectors
import subprocess
import tempfile
import time

from process_lifecycle import ProcessScope

MAX_OUTPUT = 1024 * 1024


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
