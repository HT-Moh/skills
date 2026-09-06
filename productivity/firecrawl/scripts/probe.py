#!/usr/bin/env python3
"""Probe a Firecrawl deployment and report which endpoints actually serve.

Self-hosted deployments disable routes, run without a model provider, or restrict egress
DNS. The upstream docs describe the hosted service, so they cannot answer "does this
instance support crawl". Only a live call can. This writes the answer as JSON and as a
developer-facing Markdown guide, so both stay in step with one run.

  FIRECRAWL_URL=https://firecrawl.example.com FIRECRAWL_TOKEN=... \
      python3 probe.py --json capabilities.json --markdown CLIENT-GUIDE.md
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 45
JOB_POLL_SECONDS = 5
JOB_POLL_LIMIT = 12
EMPTY_RETRIES = 3

WORKS, EMPTY, FORBIDDEN, MISSING, FAILED = "works", "empty", "forbidden", "missing", "failed"

# A reachable third-party host is required: an instance with restricted egress DNS resolves
# some hosts and not others, and that difference is exactly what we are probing for.
PROBES = [
    ("search", "POST", "/v2/search", {"query": "open source web crawler", "limit": 5}),
    ("search:research", "POST", "/v2/search",
     {"query": "open source web crawler", "categories": ["research"], "limit": 5}),
    ("search:github", "POST", "/v2/search",
     {"query": "open source web crawler", "categories": ["github"], "limit": 5}),
    ("scrape", "POST", "/v2/scrape", {"url": "{probe_url}", "formats": ["markdown"]}),
    ("map", "POST", "/v2/map", {"url": "{probe_url}", "limit": 5}),
    ("research", "POST", "/v2/research/search-papers", {"query": "firecrawl"}),
]

JOB_PROBES = [
    ("crawl", "/v2/crawl", {"url": "{probe_url}", "limit": 2}),
    ("batch_scrape", "/v2/batch/scrape", {"urls": ["{probe_url}"], "formats": ["markdown"]}),
]


def first_env(*names):
    """First non-empty value among these variables.

    The firecrawl-mcp package reads FIRECRAWL_API_URL / FIRECRAWL_API_KEY, while shell and
    application setups commonly use FIRECRAWL_URL / FIRECRAWL_TOKEN. Accept both so one
    environment serves the MCP server and this script.
    """
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def call(base, token, method, path, body):
    """Return (status_code, parsed_body_or_none). Never raises for HTTP errors."""
    payload = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=payload, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        return error.code, None
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as error:
        print(f"  {path}: {type(error).__name__}", file=sys.stderr)
        return 0, None


def classify(status, body):
    """Map one response to a capability verdict."""
    if status == 403:
        return FORBIDDEN
    if status == 404:
        return MISSING
    if status != 200 or not isinstance(body, dict):
        return FAILED
    if body.get("success") is False:
        return FAILED
    return WORKS if has_payload(body) else EMPTY


def has_payload(body):
    """True when the response carries actual results rather than an empty envelope."""
    data = body.get("data")
    if isinstance(data, dict):
        return any(data.get(key) for key in ("web", "markdown", "html", "developer"))
    if isinstance(data, list):
        return bool(data)
    return bool(body.get("links"))


def attempt(base, token, method, path, body):
    """Call an endpoint until it yields a payload, or the retries run out.

    Search returns `success: true` with no rows and `creditsUsed: 0` on a sizeable minority
    of calls. One shot would report a working endpoint as empty, so an empty verdict is only
    believed after EMPTY_RETRIES consecutive empty answers.
    """
    state = status = None
    for _ in range(EMPTY_RETRIES):
        status, payload = call(base, token, method, path, body)
        state = classify(status, payload)
        if state != EMPTY:
            return state, status
    return state, status


def run_job(base, token, path, body):
    """Start an async job and poll it. Returns a verdict plus how long it took."""
    status, started = call(base, token, "POST", path, body)
    if status != 200 or not isinstance(started, dict) or not started.get("id"):
        return classify(status, started), None
    job_id = started["id"]
    started_at = time.monotonic()
    for _ in range(JOB_POLL_LIMIT):
        time.sleep(JOB_POLL_SECONDS)
        _, state = call(base, token, "GET", f"{path}/{job_id}", None)
        if isinstance(state, dict) and state.get("status") == "completed":
            return WORKS, round(time.monotonic() - started_at)
    return EMPTY, None


def probe(base, token, probe_url):
    """Probe every endpoint. Returns an ordered name -> result mapping."""
    results = {}
    for name, method, path, template in PROBES:
        body = json.loads(json.dumps(template).replace("{probe_url}", probe_url))
        state, status = attempt(base, token, method, path, body)
        results[name] = {"path": path, "state": state, "status": status}
        print(f"  {name:20} {state}")
    for name, path, template in JOB_PROBES:
        body = json.loads(json.dumps(template).replace("{probe_url}", probe_url))
        state, seconds = run_job(base, token, path, body)
        results[name] = {"path": path, "state": state, "seconds": seconds}
        print(f"  {name:20} {state}")
    return results


def render_markdown(base, results, probed_at):
    """Render the probe as a guide a developer can implement a client from."""
    reference = os.path.join(os.path.dirname(__file__), "..", "references", "api.md")
    with open(os.path.abspath(reference), encoding="utf-8") as handle:
        body = handle.read()
    rows = "\n".join(
        f"| `{result['path']}`{'' if ':' not in name else ' (' + name.split(':')[1] + ')'} "
        f"| {result['state']} |"
        for name, result in results.items()
    )
    table = f"| Endpoint | State |\n|---|---|\n{rows}"
    return (
        f"# Consuming the Firecrawl instance at {base}\n\n"
        f"Generated by `probe.py` on {probed_at}. Re-run it before trusting availability;\n"
        f"a self-hosted deployment changes what it serves without changing its version.\n\n"
        f"## Verified endpoint state\n\n{table}\n\n{body}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the raw probe result here")
    parser.add_argument("--markdown", help="write the developer guide here")
    parser.add_argument("--probe-url", default="https://arxiv.org",
                        help="third-party URL used to test scrape/crawl (default: arxiv.org)")
    args = parser.parse_args()

    base = first_env("FIRECRAWL_API_URL", "FIRECRAWL_URL").rstrip("/")
    token = first_env("FIRECRAWL_API_KEY", "FIRECRAWL_TOKEN")
    if not base or not token:
        sys.exit("set FIRECRAWL_API_URL and FIRECRAWL_API_KEY")

    print(f"probing {base}")
    probed_at = time.strftime("%Y-%m-%d %H:%M:%S")
    results = probe(base, token, args.probe_url)
    report = {"probed_at": probed_at, "base": base, "endpoints": results}

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
        print(f"wrote {args.json}")
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as handle:
            handle.write(render_markdown(base, results, probed_at))
        print(f"wrote {args.markdown}")
    if not args.json and not args.markdown:
        json.dump(report, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
