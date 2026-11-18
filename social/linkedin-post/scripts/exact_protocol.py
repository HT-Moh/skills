"""Machine-only preview boundary. Scheduling stays unavailable until receipt integration."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from exact_request import PROTOCOL, admit
from exact_runtime import snapshot
from exact_worker import run_worker

MAX_INPUT = 32768


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
