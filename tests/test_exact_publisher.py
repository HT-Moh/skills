"""Exact publisher admission never defaults into the legacy post-now path."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import pytest

SCRIPTS = Path(__file__).parents[1] / "social/linkedin-post/scripts"
NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)


def load_request_module(name="exact_request"):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def request(**changes):
    text = "Exact  text.\n\nFinal line.\n"
    return {
        "protocol": "storyproof.linkedin/1", "op": "preview_exact", "request_id": "preview-1",
        "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "account_url": "https://www.linkedin.com/in/example-member/",
        "scheduled_at": "2026-11-24T07:30:00Z", "account_timezone": "Europe/Zurich",
        "audience_timezone": "Europe/Zurich", "min_lead_hours": 12,
        "runtime_digest": "a" * 64, **changes,
    }


def test_exact_request_keeps_all_text_and_resolves_account_wall_time():
    value = load_request_module().admit(request(), now=NOW)
    assert value["text"] == request()["text"]
    assert value["dateStr"] == "11/24/2026"
    assert value["timeStr"] == "8:30 AM"
    assert value["epoch_ms"] == 1795505400000


@pytest.mark.parametrize("changes", [
    {"op": "post_now"}, {"op": "schedule_exact"}, {"protocol": "storyproof.linkedin/2"},
    {"scheduled_at": None}, {"scheduled_at": "2026-11-24T07:30:01Z"},
    {"scheduled_at": "2026-11-18T01:00:00Z"}, {"scheduled_at": "2027-10-31T00:30:00Z"},
    {"account_url": "https://www.linkedin.com/in/me/"},
    {"account_url": "https://linkedin.com.evil.example/in/person/"},
    {"account_url": "https://www.linkedin.com/in/person/?different=true"},
    {"text_sha256": "b" * 64}, {"text": " "}, {"text": "hello\r\n"},
    {"min_lead_hours": True}, {"min_lead_hours": float("nan")},
    {"min_lead_hours": 10 ** 1000},
    {"min_lead_hours": -1}, {"runtime_digest": "latest"},
    {"account_timezone": "unknown"}, {"media": ["unexpected.png"]},
    {"confirm": True},
])
def test_unsupported_or_ambiguous_request_is_refused(changes):
    with pytest.raises(ValueError):
        load_request_module().admit(request(**changes), now=NOW)


def test_capabilities_is_machine_json_without_browser_configuration():
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "post_linkedin.py"), "--protocol", "storyproof.linkedin/1"],
        input=json.dumps({"protocol": "storyproof.linkedin/1", "op": "capabilities",
                          "request_id": "cap-1"}),
        capture_output=True, text=True, timeout=30,
        env={"PATH": __import__("os").environ["PATH"]},
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["request_id"] == "cap-1"
    assert data["operations"] == ["capabilities", "preview_exact"]
    assert data["schedule_exact"] is False
    assert len(data["runtime_digest"]) == 64


def test_node_observation_contracts():
    proc = subprocess.run(["node", "--test", str(Path(__file__).with_name(
        "exact_observation.test.cjs"))], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_runtime_snapshot_cannot_follow_source_edits(tmp_path):
    source = tmp_path / "driver.js"
    source.write_text("original")
    runtime = load_request_module("exact_runtime")
    with runtime.snapshot(tmp_path) as (copied, first):
        source.write_text("changed")
        assert (copied / "driver.js").read_text() == "original"
    with runtime.snapshot(tmp_path) as (_, second):
        assert first != second


def test_runtime_snapshot_refuses_links_and_bounds_bytes(tmp_path, monkeypatch):
    runtime = load_request_module("exact_runtime")
    outside = tmp_path / "outside"
    outside.write_text("private")
    (tmp_path / "driver.js").symlink_to(outside)
    with pytest.raises((ValueError, OSError)):
        with runtime.snapshot(tmp_path):
            pytest.fail("symlink admitted")
    (tmp_path / "driver.js").unlink()
    (tmp_path / "driver.js").write_text("oversize")
    monkeypatch.setattr(runtime, "MAX_BYTES", 2)
    with pytest.raises(ValueError, match="byte limit"):
        with runtime.snapshot(tmp_path):
            pytest.fail("oversize runtime admitted")
