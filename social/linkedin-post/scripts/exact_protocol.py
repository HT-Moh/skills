"""Machine-only preview boundary. Scheduling stays unavailable until receipt integration."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from exact_request import PROTOCOL, admit
from exact_runtime import snapshot
from exact_worker import run_worker

MAX_INPUT = 32768


def relay_capture(root: Path, envelope: dict, *, upstream: int, downstream: int,
                  outdir: Path) -> None:
    """Private source-disabled sibling transport through the existing owners."""
    from exact_exchange import CaptureExchange
    from exact_capture import encode_capture
    from exact_capture_clock import verify_compatibility
    from process_lifecycle import ProcessScope
    exchange = CaptureExchange(envelope, now=datetime.now(timezone.utc))
    with ProcessScope(capture_deadline=exchange.deadline, outer_capture=True):
        context = {"capture": exchange.envelope, "outdir": str(outdir)}
        encode_capture(context)
        verify_compatibility(exchange.envelope["compatibility"], exchange.deadline)
        with snapshot(root, capture_deadline=exchange.deadline) as (runtime, digest):
            exchange.deadline.remaining()
            if digest != exchange.request["runtime_digest"]:
                raise ValueError("publisher runtime changed")
            run_worker(runtime, context, exchange=exchange, upstream=upstream, downstream=downstream)
        exchange.deadline.remaining(0)


def capture_main() -> None:
    """Public capability discovery only; a fresh request never launches a worker/browser."""
    from exact_capture import PROTOCOL as capture_protocol, CLOCK, LIMITS, fields, decode_capture, encode_capture
    from exact_capture_clock import Deadline, observe_compatibility
    from exact_exchange import CaptureExchange
    from process_output import read_initial
    try:
        body = read_initial(sys.stdin.buffer.fileno(), timeout=15, limit=LIMITS["input_bytes"])
        value = decode_capture(body)
        if value.get("kind") == "capture_capabilities_request":
            fields(value, {"protocol", "kind", "request_id"})
            if value["protocol"] != capture_protocol or _request_id(value) is None:
                raise ValueError("invalid capture capability request")
            deadline = Deadline(str(time.clock_gettime_ns(time.CLOCK_MONOTONIC) + 60_000_000_000))
            compatibility = observe_compatibility(deadline)
            with snapshot(Path(__file__).parent, capture_deadline=deadline) as (_, digest):
                result = dict(protocol=capture_protocol, kind="capture_capabilities",
                              request_id=value["request_id"], runtime_digest=digest, limits=LIMITS,
                              clock=CLOCK, max_overall_ms=300000, cleanup_ms=15000,
                              compatibility=compatibility, relay_supported=True,
                              native_capture_supported=False, schedule_exact=False)
        else:
            exchange = CaptureExchange(value, now=datetime.now(timezone.utc))
            request = exchange.request
            result = {k: value[k] for k in ("protocol", "request_key", "policy_digest",
                                           "clock", "expires_at_monotonic_ns")}
            result.update(kind="capture_terminal", terminal=dict(
                protocol=request["protocol"], request_id=request["request_id"],
                attempt_id=request["attempt_id"], request_key=exchange.request_key,
                runtime_digest=request["runtime_digest"], disposition="refused_before_submit",
                effect_started=False, reason="Native exact capture and scheduling unavailable",
                checked_at=datetime.now(timezone.utc).isoformat()))
            exchange.frame(encode_capture(result))
        sys.stdout.buffer.write(encode_capture(result))
        sys.stdout.buffer.flush()
    except (ValueError, OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(str(error)[:500], file=sys.stderr)
        raise SystemExit(1) from error


def relay_schedule(root: Path, request: dict, *, upstream: int, downstream: int,
                   outdir: Path, timeout: float = 230) -> None:
    """Private transport composition; no public dispatch path enables this yet."""
    from exact_exchange import Exchange
    exchange = Exchange(request, now=datetime.now(timezone.utc))
    with snapshot(root) as (runtime, digest):
        if digest != exchange.request["runtime_digest"]:
            raise ValueError("publisher runtime changed")
        run_worker(runtime, {"request": exchange.request, "outdir": str(outdir)},
                   exchange=exchange, upstream=upstream, downstream=downstream, timeout=timeout)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate request field")
        value[key] = item
    return value


def _request_id(raw):
    value = raw.get("request_id") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value) else None


def main(argv: list[str]) -> None:
    if argv == ["--protocol", "storyproof.linkedin.capture/1"]:
        return capture_main()
    raw = {}
    try:
        if argv != ["--protocol", PROTOCOL]:
            raise ValueError("protocol mode cannot be combined with legacy flags")
        body = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(body) > MAX_INPUT:
            raise ValueError("request too large")
        raw = json.loads(body.decode("utf-8"), object_pairs_hook=_unique)
        request = admit(raw, now=datetime.now(timezone.utc))
        with snapshot(Path(__file__).parent) as (runtime, digest):
            if request["op"] == "capabilities":
                result = {"operations": ["capabilities", "preview_exact"],
                          "schedule_exact": False, "payload_types": ["text"],
                          "runtime_digest": digest}
            else:
                if digest != request["runtime_digest"]:
                    raise ValueError("publisher runtime changed")
                # Child imports and Node require() resolve only the admitted private copy.
                outdir = tempfile.mkdtemp(prefix="linkedin-exact-preview-")
                result = run_worker(runtime, {**request, "outdir": outdir})
                result["artifacts_dir"] = outdir
                result["runtime_digest"] = digest
        result.update(protocol=PROTOCOL, request_id=request["request_id"])
    except (ValueError, OSError, subprocess.SubprocessError, RecursionError, OverflowError,
            RuntimeError) as exc:
        result = {"protocol": PROTOCOL, "request_id": _request_id(raw),
                  "disposition": "refused_pre_effect", "detail": str(exc)[:500]}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
