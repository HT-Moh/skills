"""Private snapshot worker: existing browser lifecycle, exact preview operation only."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from exact_request import PREVIEW, admit
import local_chrome
import post_linkedin


def stream_main() -> None:
    """Private worker relay; errors stay transport failures, never preview refusals."""
    from exact_exchange import Exchange, canonical, decode
    from process_output import read_initial
    value = decode(read_initial(sys.stdin.buffer.fileno(), timeout=200))
    exchange = Exchange(value["request"], now=datetime.now(timezone.utc))
    context = exchange.context
    context["exact_exchange"] = {
        "request_json": canonical(exchange.request).decode("utf-8"), "request_key": exchange.request_key}
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
