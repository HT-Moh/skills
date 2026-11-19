"""Isolated preview process and bounded ownership transfer to its supervisor."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import local_chrome
from process_lifecycle import ProcessScope, current_scope
from capture_control import CleanupContext, OMITTED
from process_output import MAX_OUTPUT, collect, relay
from profile_lease import ProfileLease, inherit_lease

# Gateway waits only 15s after TERM. All owned descendants share one 10s TERM
# deadline plus 2s KILL/reap, not a timeout per child/group. With 30s snapshot and
# 230s work, normal completion also fits the gateway's 300s outer budget.
WORKER_TIMEOUT = 230
CANCEL_GRACE = 10


def _invalid_constant(value):
    raise ValueError("non-finite worker JSON")


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate worker field")
        value[key] = item
    return value


def _result(body):
    try:
        value = json.loads(body.decode("utf-8"), parse_constant=_invalid_constant,
                           object_pairs_hook=_unique)
        if not isinstance(value, dict) or value.get("disposition") not in (
                "preview_verified", "refused_pre_effect"):
            raise ValueError("invalid worker result object")
        # Reject huge exponents (JSON decodes 1e999 as inf) and bound the encoded
        # envelope too; ASCII escaping keeps surrogate-containing strings safe.
        if len(json.dumps(value, ensure_ascii=True, allow_nan=False)) > MAX_OUTPUT:
            raise ValueError("worker output limit exceeded")
        return value
    except (UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError("invalid worker result JSON") from exc


def run_worker(runtime: Path, request: dict, *, timeout=WORKER_TIMEOUT, grace=OMITTED,
               exchange=None, upstream=None, downstream=None):
    deadline = getattr(exchange, "deadline", None)
    owner = ProcessScope(grace=grace, capture_deadline=deadline, outer_capture=True) \
        if deadline is not None else contextlib.nullcontext()
    with owner:
        return _run_worker(runtime, request, timeout=timeout, grace=grace, exchange=exchange,
                           upstream=upstream, downstream=downstream)


def _run_worker(runtime: Path, request: dict, *, timeout=WORKER_TIMEOUT, grace=OMITTED,
               exchange=None, upstream=None, downstream=None):
    """Execute admitted snapshot; hold kept-profile lease through fallback cleanup.

    Trust boundary: the already-running protocol launcher, sys.executable and its
    installed standard library/extension modules are trusted host runtime, not
    part of the copied publisher digest. Child isolation cannot undo code that
    ran during the launcher's own Python startup.
    -I ignores Python environment and excludes cwd; -S disables site, .pth,
    sitecustomize and usercustomize. Only the admitted snapshot is added to that
    isolated stdlib path. No inherited site-packages or parent sys.path is copied.
    Native loader/interpreter tampering by the host user is outside this boundary.
    """
    runtime = runtime.resolve()
    capture_deadline = getattr(exchange, "deadline", None)
    payload = json.dumps(request, ensure_ascii=True, allow_nan=False).encode() + b"\n"
    if capture_deadline is not None:
        from exact_capture import decode_capture
        from exact_capture_clock import verify_compatibility
        decode_capture(payload)
        verify_compatibility(exchange.envelope["compatibility"], capture_deadline)
        capture_deadline.remaining()
    profile = local_chrome.kept_profile() if local_chrome.configured_chrome() else None
    lease = ProfileLease(profile) if profile else contextlib.nullcontext(None)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("PYTHON") and key not in {"NODE_PATH", "NODE_OPTIONS"}}
    bootstrap = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from exact_worker import worker_main; worker_main()"
    )
    with lease as held, tempfile.TemporaryFile() as stdin:
        stdin.write(json.dumps(request, ensure_ascii=True, allow_nan=False).encode("ascii"))
        stdin.seek(0)
        passed = (held.fd,) if held is not None else ()
        control_args = []
        if capture_deadline is not None:
            control = current_scope().capture_context
            control_args = control.arguments("worker")
            passed += (control.fd,)
        scope = ProcessScope(grace=grace, capture_deadline=capture_deadline,
                             outer_capture=capture_deadline is not None)
        try:
            with scope:
                proc = scope.spawn(
                    [sys.executable, "-I", "-S", "-B", "-c", bootstrap, str(runtime),
                     str(held.fd if held is not None else -1),
                       str(profile.resolve()) if profile else "", "stream" if exchange else "preview",
                        str(capture_deadline.expiry) if capture_deadline else "", *control_args],
                    stdin=subprocess.PIPE if exchange else stdin,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    env=env, pass_fds=passed, close_fds=True, start_new_session=True,
                )
                if exchange is not None:
                    relay(proc, scope, input=payload,
                           upstream=upstream, downstream=downstream, frame=exchange.frame,
                           acknowledgment=exchange.acknowledgment, timeout=timeout,
                           capture_deadline=capture_deadline)
                    return None
                result = collect(proc, scope, timeout=timeout)
                if result.returncode:
                    raise ValueError("preview driver failed before submission")
                return _result(result.stdout)
        finally:
            if held is not None and not scope.errors:
                held.clean_singleton(scope.identities)


def worker_main():
    """Called only by the isolated bootstrap, before importing preview code."""
    lease_fd = int(sys.argv[2])
    deadline = None
    control = None
    if len(sys.argv) > 5 and sys.argv[5]:
        from exact_capture_clock import Deadline
        control = CleanupContext.from_arguments(sys.argv[5], sys.argv[6:], lease_fd=lease_fd)
        try:
            deadline = Deadline(sys.argv[5])
        except BaseException:
            control.close()
            raise
    with ProcessScope(capture_deadline=deadline, capture_context=control):
        if lease_fd >= 0:
            inherit_lease(sys.argv[3], lease_fd)
        import exact_preview
        if len(sys.argv) > 4 and sys.argv[4] == "stream":
            exact_preview.stream_main(capture_deadline=deadline)
        else:
            exact_preview.main()
