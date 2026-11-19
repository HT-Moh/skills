"""Private snapshot worker: existing browser lifecycle, exact preview operation only."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from exact_request import PREVIEW, admit
import local_chrome
import post_linkedin


def stream_main(*, capture_deadline=None) -> None:
    """Private worker relay; errors stay transport failures, never preview refusals."""
    from exact_exchange import Exchange, CaptureExchange, canonical, decode
    from process_output import read_initial
    raw = read_initial(sys.stdin.buffer.fileno(),
                       timeout=capture_deadline.remaining() if capture_deadline else 200)
    if capture_deadline is not None:
        from exact_capture import decode_capture, fields
        from exact_capture_clock import verify_compatibility
        value = decode_capture(raw)
        fields(value, {"capture", "outdir"})
        exchange = CaptureExchange(value["capture"], now=datetime.now(timezone.utc))
        if exchange.deadline.expiry != capture_deadline.expiry:
            raise ValueError("worker capture deadline changed")
        verify_compatibility(exchange.envelope["compatibility"], capture_deadline)
    else:
        value = decode(raw)
        exchange = Exchange(value["request"], now=datetime.now(timezone.utc))
    context = exchange.context
    context["exact_exchange"] = {
        "request_json": canonical(exchange.request).decode("utf-8"), "request_key": exchange.request_key}
    if capture_deadline is not None:
        context["exact_exchange"].update(exchange.envelope)
    url, token = post_linkedin.resolve_browser()
    cookies = []
    if post_linkedin.needs_cookies():
        path = os.environ.get("LINKEDIN_COOKIES")
        if not path:
            raise ValueError("publisher login unavailable")
        cookies = post_linkedin.to_puppeteer(json.loads(Path(path).read_text()))
    post_linkedin._run_ws(url, token, {**context, "cookies": cookies},
                         [], Path(value["outdir"]), exchange=exchange)


def main() -> None:
    value = json.load(sys.stdin)
    request = admit({key: value[key] for key in PREVIEW}, now=datetime.now(timezone.utc))
    # local_chrome acquires the shared atomic lease before checking SingletonLock
    # and holds it through startup, use, group teardown and owned lock cleanup.
    url, token = post_linkedin.resolve_browser()
    cookies = []
    if post_linkedin.needs_cookies():
        path = os.environ.get("LINKEDIN_COOKIES")
        if not path:
            raise ValueError("publisher login unavailable")
        cookies = post_linkedin.to_puppeteer(json.loads(Path(path).read_text()))
    result = post_linkedin._run_ws(url, token, {**request, "cookies": cookies},
                                   [], Path(value["outdir"]))
    if not isinstance(result, dict):
        raise ValueError("invalid preview result object")
    if result.get("disposition") != "preview_verified":
        result["disposition"] = "refused_pre_effect"
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    with local_chrome.owned_lifecycle():
        main()
