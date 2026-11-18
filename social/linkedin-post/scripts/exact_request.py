"""Strict schedule-preview admission; no browser, filesystem or default publication."""
from datetime import datetime, timezone
import hashlib
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROTOCOL = "storyproof.linkedin/1"
BASE = {"protocol", "op", "request_id"}
PREVIEW = BASE | {
    "text", "text_sha256", "account_url", "scheduled_at", "account_timezone",
    "audience_timezone", "min_lead_hours", "runtime_digest",
}


def admit(raw: dict, *, now: datetime) -> dict:
    """Validate once; return transport context with exact bytes and resolved wall time."""
    if not isinstance(raw, dict) or raw.get("protocol") != PROTOCOL:
        raise ValueError("unsupported protocol")
    if not isinstance(raw.get("request_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,100}", raw["request_id"]
    ):
        raise ValueError("invalid request_id")
    if raw.get("op") == "capabilities" and set(raw) == BASE:
        return dict(raw)
    if raw.get("op") != "preview_exact" or set(raw) != PREVIEW:
        raise ValueError("unsupported operation or request fields")
    text = raw["text"]
    if (not isinstance(text, str) or not text.strip() or len(text) > 3000
            or any(ord(c) < 32 and c != "\n" for c in text)):
        raise ValueError("unsupported text")
    try:
        text_digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ValueError("invalid UTF-8 text") from exc
    if text_digest != raw["text_sha256"]:
        raise ValueError("text digest mismatch")
    if not isinstance(raw["runtime_digest"], str) or not re.fullmatch(
        r"[a-f0-9]{64}", raw["runtime_digest"]
    ):
        raise ValueError("invalid runtime_digest")
    url = raw["account_url"]
    if (not isinstance(url, str)
            or not re.fullmatch(r"https://www\.linkedin\.com/in/[a-zA-Z0-9_-]+/", url)
            or url.lower() == "https://www.linkedin.com/in/me/"):
        raise ValueError("concrete canonical account profile URL required")
    lead = raw["min_lead_hours"]
    if type(lead) not in (int, float) or not 0 < lead <= 2160 or not math.isfinite(lead):
        raise ValueError("invalid minimum lead")
    instant = raw["scheduled_at"]
    if not isinstance(instant, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z", instant
    ):
        raise ValueError("UTC minute required")
    scheduled = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    if (scheduled - now).total_seconds() < lead * 3600:
        raise ValueError("minimum lead expired")
    try:
        zones = [ZoneInfo(raw[key]) for key in ("account_timezone", "audience_timezone")]
    except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
        raise ValueError("invalid timezone") from exc
    for zone in zones:
        wall = scheduled.astimezone(zone)
        if wall.replace(fold=0).utcoffset() != wall.replace(fold=1).utcoffset():
            raise ValueError("ambiguous local schedule time")
    wall = scheduled.astimezone(zones[0])
    return {**raw, "confirm": False, "schedule": True,
            "epoch_ms": int(scheduled.timestamp() * 1000),
            "dateStr": wall.strftime("%m/%d/%Y"), "timeStr": wall.strftime("%-I:%M %p"),
            "monthLabel": wall.strftime("%B %Y")}
