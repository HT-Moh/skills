"""Private schedule exchange contracts; public capability remains unavailable."""
from datetime import datetime, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from exact_request import PREVIEW, admit

SCHEDULE = PREVIEW | {"attempt_id", "authorization", "operation_key", "preview_key"}
CORRELATION = {"protocol", "request_id", "attempt_id", "request_key"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate exchange field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite exchange value")


def decode(raw: bytes) -> dict:
    try:
        if len(raw) > 65536:
            raise ValueError("exchange frame limit exceeded")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)
        if not isinstance(value, dict):
            raise ValueError("exchange object required")
        json.dumps(value, allow_nan=False).encode("utf-8")
        return value
    except (UnicodeError, RecursionError, OverflowError) as error:
        raise ValueError("invalid exchange JSON") from error


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


class Exchange:
    """Freeze original wire identity separately from derived browser context."""

    def __init__(self, request: dict, *, now: datetime):
        if not isinstance(request, dict) or set(request) != SCHEDULE or request["op"] != "schedule_exact":
            raise ValueError("unsupported schedule request")
        if type(request["min_lead_hours"]) is not int:
            raise ValueError("integer minimum lead required")
        if not isinstance(request["attempt_id"], str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,100}", request["attempt_id"]):
            raise ValueError("invalid attempt identity")
        for key in ("authorization", "operation_key", "preview_key"):
            if not isinstance(request[key], str) or not re.fullmatch(r"[a-f0-9]{64}", request[key]):
                raise ValueError("invalid schedule identity")
        self._raw = canonical(request)
        self._key = hashlib.sha256(self._raw).hexdigest()
        context = admit({**{key: request[key] for key in PREVIEW}, "op": "preview_exact"}, now=now)
        self._context = canonical({**context, **request})
        self._started = now

    @property
    def request_key(self) -> str:
        return self._key

    @property
    def request(self) -> dict:
        return decode(self._raw)

    @property
    def context(self) -> dict:
        return decode(self._context)

    def _correlation(self) -> dict:
        request = self.request
        return {key: request[key] for key in CORRELATION - {"request_key"}} | {"request_key": self._key}

    def acknowledgment(self, raw: bytes) -> None:
        expected = self._correlation() | {"disposition": "submit_acknowledged"}
        if decode(raw) != expected:
            raise ValueError("acknowledgment differs from admitted request")

    def _time(self, text) -> None:
        try:
            observed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if not self._started <= observed <= datetime.now(timezone.utc):
                raise ValueError("observation outside invocation")
        except (AttributeError, TypeError) as error:
            raise ValueError("invalid observation time") from error

    def frame(self, raw: bytes) -> str:
        value, request = decode(raw), self.request
        if any(value.get(key) != expected for key, expected in self._correlation().items()):
            raise ValueError("frame differs from admitted request")
        if value.get("runtime_digest") != request["runtime_digest"]:
            raise ValueError("frame runtime changed")
        base = CORRELATION | {"disposition", "runtime_digest"}
        if value.get("disposition") == "ready_to_submit":
            if set(value) != base | {"evidence"}:
                raise ValueError("invalid ready fields")
            self._evidence(value["evidence"])
            return "ready"
        if (value.get("disposition") not in ("refused_before_submit", "uncertain")
                or set(value) != base | {"effect_started", "reason", "checked_at"}
                or type(value["effect_started"]) is not bool
                or (value["disposition"] == "refused_before_submit" and value["effect_started"])
                or not isinstance(value["reason"], str) or not 1 <= len(value["reason"]) <= 4096):
            raise ValueError("invalid terminal fields")
        self._time(value["checked_at"])
        return "terminal"

    def _evidence(self, evidence) -> None:
        request, context = self.request, self.context
        if not isinstance(evidence, dict) or set(evidence) != {
                "actor", "schedule", "browser_timezone", "text_sha256", "text_contract",
                "attachments", "checked_at", "posting_at"}:
            raise ValueError("invalid ready evidence")
        instant = datetime.fromisoformat(request["scheduled_at"].replace("Z", "+00:00"))
        wall = instant.astimezone(ZoneInfo(request["account_timezone"]))
        expected = {
            "actor": {"account_url": request["account_url"],
                      "selected_actor_key": "ShareBoxactorState_Self_Self",
                      "checked_count": 1, "source": "linkedin-sdui-personal-actor-v1"},
            "schedule": {"epoch_ms": context["epoch_ms"],
                         "date": {"day": wall.day, "month": wall.month, "year": wall.year},
                         "minutes": wall.hour * 60 + wall.minute,
                         "source": "linkedin-confirm-schedule-post-v1"},
            "browser_timezone": request["account_timezone"], "text_sha256": request["text_sha256"],
            "text_contract": "prosemirror-paragraph-text-v1", "attachments": [],
        }
        # Canonical equality distinguishes JSON booleans and numbers.
        if canonical({key: evidence[key] for key in expected}) != canonical(expected):
            raise ValueError("ready evidence differs from request")
        if not isinstance(evidence["posting_at"], str) or not 1 <= len(evidence["posting_at"]) <= 256:
            raise ValueError("invalid posting label")
        self._time(evidence["checked_at"])
        checked = datetime.fromisoformat(evidence["checked_at"].replace("Z", "+00:00"))
        if (instant - checked).total_seconds() < request["min_lead_hours"] * 3600:
            raise ValueError("minimum lead expired")
