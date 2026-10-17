#!/usr/bin/env python3
"""Post (or natively schedule) to LinkedIn through a local Chrome when $LINKEDIN_LOCAL_CHROME
names one (see local_chrome.py), else through a self-hosted browserless instance.

Deterministic glue only — no judgement lives here:
  1. start the browser: a local Chrome, on the kept profile's own login when
     $LINKEDIN_CHROME_PROFILE is set; or browserless with the exported cookies from
     --cookies / $LINKEDIN_COOKIES, converted to Puppeteer setCookie shape
  2. render the schedule time as LinkedIn's date/time strings, in the account's timezone
  3. run linkedin_ws.js over CDP/WebSocket (or, with --http, POST linkedin_flow.js to
     $BROWSERLESS_URL/function)
  4. save every screenshot and print the verdict

Never prints cookie values. Defaults to a DRY RUN — nothing is published unless --confirm.

Usage:
  post_linkedin.py --text "…"            # dry-run preview, post-now composer
  post_linkedin.py --file post.md --confirm
  post_linkedin.py --text "…" --at 2026-08-12T09:00              # dry-run schedule
  post_linkedin.py --text "…" --at 2026-08-12T09:00 --confirm    # really schedule
"""
import argparse, base64, json, os, re, signal, subprocess, sys, tempfile, time
from datetime import datetime
from pathlib import Path

import local_chrome

HERE = Path(__file__).resolve().parent
FLOW_JS = HERE / "linkedin_flow.js"
WS_JS = HERE / "linkedin_ws.js"
# The driver's watchdog ends a stuck run at 200 s; this is the backstop behind it. The
# pipeline allows the whole poster 300 s: this, plus up to 30 s Chrome startup and 10 s stop.
DRIVER_TIMEOUT_S = 240
_SAMESITE = {"no_restriction": "None", "unspecified": None, "lax": "Lax",
             "strict": "Strict", "none": "None", None: None}


def to_puppeteer(raw):
    """Chrome-extension cookie export -> list of Puppeteer setCookie objects."""
    out = []
    for c in raw:
        ck = {"name": c["name"], "value": c["value"],
              "domain": c["domain"], "path": c.get("path", "/"),
              "secure": bool(c.get("secure", False)),
              "httpOnly": bool(c.get("httpOnly", False))}
        ss = _SAMESITE.get((c.get("sameSite") or "").lower() if isinstance(c.get("sameSite"), str) else c.get("sameSite"))
        if ss:
            ck["sameSite"] = ss
        if not c.get("session") and c.get("expirationDate"):
            ck["expires"] = float(c["expirationDate"])
        out.append(ck)
    return out


def resolve_browserless():
    """(url, token) from the environment, or exit. One owner of this check so callers
    (poster, tracker) don't each re-derive it."""
    url = os.environ.get("BROWSERLESS_URL")
    token = os.environ.get("BROWSERLESS_TOKEN")
    if not url or not token:
        sys.exit("set BROWSERLESS_URL and BROWSERLESS_TOKEN (see the browserless skill)")
    return url, token


def resolve_browser():
    """(url, token) of browserless, or (None, None) when $LINKEDIN_LOCAL_CHROME runs the WS
    driver on a local Chrome, which needs neither."""
    return (None, None) if local_chrome.configured_chrome() else resolve_browserless()


def needs_cookies() -> bool:
    """False when the kept profile holds the poster's own login: exported cookies are then
    never loaded."""
    return local_chrome.kept_profile() is None


def _drive(node: str, ws_ctx: dict) -> subprocess.CompletedProcess:
    return subprocess.run([node, str(WS_JS)], input=json.dumps(ws_ctx),
                          capture_output=True, text=True, timeout=DRIVER_TIMEOUT_S)


def _run_ws(url: str, token: str, ctx: dict, media_paths, outdir: Path,
            document_path=None, document_title=None) -> dict:
    """Default path: drive browserless over CDP/WebSocket via the Node driver.

    A WS session with a keepalive is immune to the browserless VIP's 50s idle timeout, so
    long flows (video processing) and clean confirmation replies both work. The Node driver
    saves screenshots directly to outdir and prints one JSON result.
    """
    import shutil
    node = shutil.which("node")
    if not node:
        sys.exit("node not found on PATH — the WS driver needs Node. Install Node or pass --http.")
    ws_ctx = dict(ctx)
    ws_ctx.update(mediaPaths=(media_paths or []),
                  mediaPath=(media_paths[0] if media_paths else None),
                  documentPath=document_path, documentTitle=document_title, outdir=str(outdir))
    chrome = local_chrome.configured_chrome()
    if chrome:
        if local_chrome.kept_profile():
            # The profile holds the poster's own login: loading exported cookies over it is
            # what made LinkedIn end the user's login.
            ws_ctx.update(cookies=[], keptLogin=True)
        with local_chrome.devtools_endpoint(chrome) as ws_ep:
            proc = _drive(node, {**ws_ctx, "wsEndpoint": ws_ep, "localBrowser": True})
    else:
        proc = _drive(node, {**ws_ctx, "wsEndpoint": re.sub(r"^http", "ws", url) + f"?token={token}"})
    if proc.returncode != 0:
        sys.exit(f"WS driver failed (rc={proc.returncode}): {proc.stderr.strip()[-400:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit(f"WS driver produced non-JSON output.\nstdout: {proc.stdout[:300]}\n"
                 f"stderr: {proc.stderr[-300:]}")


def _run_http(url: str, token: str, ctx: dict, media_path, outdir: Path, confirm: bool) -> dict:
    """Legacy path: one stateless /function POST. Subject to the VIP 50s idle timeout."""
    ctx = dict(ctx)
    ctx["media"] = None
    if media_path:
        mp = Path(media_path)
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".mp4": "video/mp4",
                ".mov": "video/quicktime", ".webm": "video/webm"}.get(mp.suffix.lower(),
                                                                       "application/octet-stream")
        ctx["media"] = {"b64": base64.b64encode(mp.read_bytes()).decode(), "name": mp.name, "mime": mime}
    body = json.dumps({"code": FLOW_JS.read_text(), "context": ctx})
    endpoint = f"{url}/function?token={token}&timeout=120000"
    attempts = 1 if confirm else 3   # never retry a confirm — a cut reply may have scheduled already
    res, last = None, ""
    for attempt in range(attempts):
        proc = subprocess.run(["curl", "-sS", "--max-time", "150", "-X", "POST", endpoint,
                               "-H", "Content-Type: application/json", "--data-binary", "@-"],
                              input=body, capture_output=True, text=True)
        if proc.returncode != 0:
            last = f"curl rc={proc.returncode}: {proc.stderr.strip()[-160:]}"
        else:
            try:
                res = json.loads(proc.stdout); break
            except json.JSONDecodeError:
                last = f"non-JSON reply: {proc.stdout[:160]}"
        if attempt < attempts - 1:
            time.sleep(3 * (attempt + 1))
    if res is None:
        if confirm:
            sys.exit(f"UNKNOWN — reply cut ({last}). Post MAY be scheduled; check LinkedIn before re-running.")
        sys.exit(f"browserless call failed after {attempts} attempts: {last}")
    data = res.get("data", res)
    for name, b64 in (data.get("shots") or {}).items():
        (outdir / f"{name}.jpg").write_bytes(base64.b64decode(b64))
    data.pop("shots", None)
    return data


def _exit_on_sigterm(signum, frame):
    """A caller that gives up sends SIGTERM. Exiting through Python, not dying at once, runs
    the cleanup that kills the driver and closes the local Chrome holding the kept profile."""
    sys.exit("poster stopped by SIGTERM")


def main():
    signal.signal(signal.SIGTERM, _exit_on_sigterm)
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="post body")
    src.add_argument("--file", help="file whose contents are the post body")
    ap.add_argument("--cookies", default=os.environ.get("LINKEDIN_COOKIES"),
                    help="exported linkedin.json, for a run without a kept profile "
                         "(default $LINKEDIN_COOKIES)")
    ap.add_argument("--at", help="schedule time as ISO 'YYYY-MM-DDTHH:MM', typed VERBATIM "
                    "into LinkedIn (interpreted in the account's own timezone). Omit = post now.")
    ap.add_argument("--media", action="append",
                    help="path to an image/gif/video to attach (uploaded through the composer). "
                         "Repeat --media for a multi-image post (carousel). WS path only for >1.")
    ap.add_argument("--document", help="path to a PDF/DOC/DOCX/PPT/PPTX to post as a LinkedIn "
                    "document (the swipeable card with a download button). One per post, and "
                    "not combinable with --media. WS path only.")
    ap.add_argument("--document-title", help="caption shown on the document card. "
                    "Defaults to the file name.")
    ap.add_argument("--http", action="store_true",
                    help="use the legacy stateless /function HTTP path instead of WS/CDP "
                         "(subject to the browserless proxy's 50s idle timeout). Default is WS.")
    ap.add_argument("--confirm", action="store_true",
                    help="actually publish/schedule; without it the flow stops at a screenshot")
    ap.add_argument("--outdir", default=tempfile.mkdtemp(prefix="li-post-"))
    args = ap.parse_args()

    # --http always runs on browserless.
    url, token = resolve_browserless() if args.http else resolve_browser()

    text = args.text if args.text is not None else Path(args.file).read_text()
    if not text.strip():
        sys.exit("empty post body")

    if needs_cookies() and not args.cookies:
        sys.exit(f"set LINKEDIN_COOKIES or pass --cookies, or log in once on a kept profile "
                 f"(${local_chrome.PROFILE_ENV}, see local_chrome.py)")
    cookies = to_puppeteer(json.loads(Path(args.cookies).read_text())) if needs_cookies() else []
    if needs_cookies() and not any(c["name"] == "li_at" for c in cookies):
        sys.exit(f"{args.cookies} has no li_at cookie — not a LinkedIn session export")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ctx = {"cookies": cookies, "text": text, "confirm": bool(args.confirm),
           "schedule": False, "dateStr": None, "timeStr": None}
    if args.at:
        # The LinkedIn schedule dialog interprets the typed time in the ACCOUNT's own
        # timezone, NOT the host's. We do NOT convert: we type the wall-clock time exactly
        # as given, and the driver checks LinkedIn's "Posting at ..." echo against it.
        # Converting here would silently shift the hour.
        dt = datetime.fromisoformat(args.at)
        ctx["schedule"] = True
        ctx["dateStr"] = dt.strftime("%-m/%-d/%Y")       # typed into the Date field, e.g. "8/14/2026"
        ctx["monthLabel"] = dt.strftime("%B %Y")          # e.g. "August 2026"; checks the "Posting at" echo
        ctx["timeStr"] = dt.strftime("%-I:%M %p")         # e.g. "9:00 AM"

    media_paths = []
    for m in (args.media or []):
        mp = Path(m)
        if not mp.is_file():
            sys.exit(f"--media file not found: {mp}")
        media_paths.append(str(mp.resolve()))

    document_path = None
    if args.document:
        if media_paths:
            sys.exit("--document and --media cannot be combined: LinkedIn allows one or the other.")
        if args.http:
            sys.exit("--document needs the WS driver; drop --http.")
        dp = Path(args.document)
        if not dp.is_file():
            sys.exit(f"--document file not found: {dp}")
        if dp.suffix.lower() not in {".pdf", ".doc", ".docx", ".ppt", ".pptx"}:
            sys.exit(f"LinkedIn accepts .pdf/.doc/.docx/.ppt/.pptx as documents, not {dp.suffix}")
        document_path = str(dp.resolve())
    if args.document_title and not args.document:
        sys.exit("--document-title has no effect without --document.")

    if args.http:
        if len(media_paths) > 1:
            print("warning: --http supports one image only; attaching the first. Use the WS path for multi-image.",
                  file=sys.stderr)
        data = _run_http(url, token, ctx, (media_paths[0] if media_paths else None), outdir, bool(args.confirm))
    else:
        data = _run_ws(url, token, ctx, media_paths, outdir,
                       document_path=document_path, document_title=args.document_title)

    print(json.dumps(data, indent=2))
    # Callers keep only the last lines of stdout; the full result, error included, stays here.
    (outdir / "result.json").write_text(json.dumps(data, indent=2))
    print(f"\nscreenshots -> {outdir}")
    if data.get("postingAt"):
        print(f"LinkedIn shows: {data['postingAt']}  (in the account's own timezone)")
    stage = data.get("stage")
    ok = data.get("ok")
    if ok and stage == "preview":
        print("DRY RUN — nothing published. Review the screenshots, then re-run with --confirm.")
    elif ok and stage in ("posted", "scheduled"):
        print(f"SUCCESS — {stage}.")
    else:
        print(f"FAILED at stage '{stage}'. Inspect {outdir} to see what LinkedIn showed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
