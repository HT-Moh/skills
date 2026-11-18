"""Schedule-only private admission and unchanged original-wire identity."""
from datetime import datetime, timezone
import hashlib
import json
import sys

import pytest

from test_exact_publisher import SCRIPTS, NOW, request

sys.path.insert(0, str(SCRIPTS))


def schedule(**changes):
    return request(op="schedule_exact", attempt_id="attempt-1", authorization="b" * 64,
                   operation_key="c" * 64, preview_key="d" * 64, **changes)


def exchange(**changes):
    from exact_exchange import Exchange
    return Exchange(schedule(**changes), now=NOW)


def test_request_key_binds_original_fields_not_browser_context():
    value = exchange()
    expected = json.dumps(schedule(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert value.request_key == hashlib.sha256(expected.encode()).hexdigest()
    assert value.context["dateStr"] == "11/24/2026"
    assert "dateStr" not in value.request
    assert value.context["op"] == "schedule_exact"


def test_mutating_returned_context_cannot_change_ack_identity():
    value = exchange()
    value.context["attempt_id"] = "other"
    value.request["text"] = "other"
    value.acknowledgment(json.dumps({
        "protocol": schedule()["protocol"], "disposition": "submit_acknowledged",
        "request_id": schedule()["request_id"], "attempt_id": "attempt-1",
        "request_key": value.request_key,
    }).encode() + b"\n")


@pytest.mark.parametrize("change", [
    {"attempt_id": ""}, {"attempt_id": "x" * 101}, {"authorization": "latest"},
    {"operation_key": None}, {"preview_key": "A" * 64}, {"min_lead_hours": 12.0},
    {"confirm": True}, {"unexpected": True},
])
def test_private_schedule_admission_is_strict(change):
    from exact_exchange import Exchange
    with pytest.raises(ValueError):
        Exchange({**schedule(), **change}, now=NOW)


@pytest.mark.parametrize("body", [
    b'{"disposition":"submit_acknowledged","disposition":"submit_acknowledged"}\n',
    b"\xff\n", b"{}\n{}\n", b"{}\n{", b'{"value":NaN}\n', b"[]\n",
])
def test_invalid_ack_is_rejected(body):
    with pytest.raises(ValueError):
        exchange().acknowledgment(body)


def test_matching_terminal_must_have_exact_fields_and_current_time():
    value = exchange()
    terminal = dict(protocol=schedule()["protocol"], disposition="uncertain",
                    request_id=schedule()["request_id"], attempt_id="attempt-1",
                    request_key=value.request_key, runtime_digest="a" * 64,
                    effect_started=False, reason="offline callback", checked_at=NOW.isoformat())
    assert value.frame(json.dumps(terminal).encode()) == "terminal"
    for changes in ({"attempt_id": "other"}, {"effect_started": 0},
                    {"extra": True}, {"checked_at": "2000-01-01T00:00:00Z"},
                    {"checked_at": "2999-01-01T00:00:00Z"}, {"reason": ""}):
        with pytest.raises(ValueError):
            value.frame(json.dumps({**terminal, **changes}).encode())
