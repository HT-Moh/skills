#!/usr/bin/env python3
"""Post (or natively schedule) to LinkedIn through a self-hosted browserless instance,
authenticating with an exported-cookie JSON file.

Deterministic glue only — no judgement lives here:
  1. convert Chrome-extension cookies -> Puppeteer setCookie shape
  2. render the schedule time as LinkedIn's LOCAL date/time strings
  3. POST scripts/linkedin_flow.js to $BROWSERLESS_URL/function with a context payload
  4. save every returned screenshot and print a one-line verdict

Never prints cookie values. Defaults to a DRY RUN — nothing is published unless --confirm.

Usage:
  post_linkedin.py --text "…"            # dry-run preview, post-now composer
  post_linkedin.py --file post.md --confirm
  post_linkedin.py --text "…" --at 2026-08-12T09:00 --tz Europe/Zurich   # dry-run schedule
  post_linkedin.py --text "…" --at 2026-08-12T09:00 --confirm            # really schedule
"""
import argparse, base64, json, os, re, subprocess, sys, tempfile, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLOW_JS = HERE / "linkedin_flow.js"
WS_JS = HERE / "linkedin_ws.js"
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


def _run_ws(url: str, token: str, ctx: dict, media_path, outdir: Path) -> dict:
    """Default path: drive browserless over CDP/WebSocket via the Node driver.

    A WS session with a keepalive is immune to the browserless VIP's 50s idle timeout, so
    long flows (video processing) and clean confirmation replies both work. The Node driver
    saves screenshots directly to outdir and prints one JSON result.
    """
    import shutil
    node = shutil.which("node")
    if not node:
        sys.exit("node not found on PATH — the WS driver needs Node. Install Node or pass --http.")
    ws_ep = re.sub(r"^http", "ws", url) + f"?token={token}"
    ws_ctx = dict(ctx)
    ws_ctx.update(wsEndpoint=ws_ep, mediaPath=media_path, outdir=str(outdir))
    proc = subprocess.run([node, str(WS_JS)], input=json.dumps(ws_ctx),
                          capture_output=True, text=True, timeout=300)
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


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="post body")
    src.add_argument("--file", help="file whose contents are the post body")
    ap.add_argument("--cookies", default=os.environ.get("LINKEDIN_COOKIES",
                    "/media/bicatalyst/79c246d3-d109-43c4-89f7-33feaac39dee2/src/cookies/linkedin.json"))
    ap.add_argument("--at", help="schedule time as ISO 'YYYY-MM-DDTHH:MM', typed VERBATIM "
                    "into LinkedIn (interpreted in the account's own timezone). Omit = post now.")
    ap.add_argument("--media", help="path to an image/gif/video to attach (uploaded through the composer)")
    ap.add_argument("--http", action="store_true",
                    help="use the legacy stateless /function HTTP path instead of WS/CDP "
                         "(subject to the browserless proxy's 50s idle timeout). Default is WS.")
    ap.add_argument("--confirm", action="store_true",
                    help="actually publish/schedule; without it the flow stops at a screenshot")
    ap.add_argument("--outdir", default=tempfile.mkdtemp(prefix="li-post-"))
    args = ap.parse_args()

    url, token = resolve_browserless()

    text = args.text if args.text is not None else Path(args.file).read_text()
    if not text.strip():
        sys.exit("empty post body")

    cookies = to_puppeteer(json.loads(Path(args.cookies).read_text()))
    if not any(c["name"] == "li_at" for c in cookies):
        sys.exit(f"{args.cookies} has no li_at cookie — not a LinkedIn session export")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ctx = {"cookies": cookies, "text": text, "confirm": bool(args.confirm),
           "schedule": False, "dateStr": None, "timeStr": None}
    if args.at:
        # The LinkedIn schedule dialog interprets the typed time in the ACCOUNT's own
        # timezone (shown in its subtitle), NOT the host's. We do NOT convert: we type the
        # wall-clock time exactly as given and echo back the dialog's timezone line so the
        # caller can confirm the zone. Converting here would silently shift the hour.
        dt = datetime.fromisoformat(args.at)
        ctx["schedule"] = True
        ctx["dateStr"] = dt.strftime("%-m/%-d/%Y")       # for the summary/echo only
        ctx["dayLabel"] = dt.strftime("%B %-d, %Y")       # calendar cell aria-label, e.g. "August 14, 2026"
        ctx["monthLabel"] = dt.strftime("%B %Y")          # e.g. "August 2026" (for month navigation)
        ctx["timeStr"] = dt.strftime("%-I:%M %p")         # e.g. "9:00 AM"

    media_path = None
    if args.media:
        mp = Path(args.media)
        if not mp.is_file():
            sys.exit(f"--media file not found: {mp}")
        media_path = str(mp.resolve())

    if args.http:
        data = _run_http(url, token, ctx, media_path, outdir, bool(args.confirm))
    else:
        data = _run_ws(url, token, ctx, media_path, outdir)

    print(json.dumps(data, indent=2))
    print(f"\nscreenshots -> {outdir}")
    if data.get("tzLine"):
        print(f"LinkedIn timezone: {data['tzLine']}  (the --at time was typed in THIS zone)")
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
