import fcntl
import json
import os
import stat

import pytest

import plan_store
from plan_schema import PlanError

SETTINGS = "~/.claude/settings.json"


def v2_item(id="P1-01", status="proposed"):
    return {"id": id, "phase": 1, "title": "t", "risk": "safe", "why": "w", "evidence": "e",
            "docs": "https://x", "impact": "i", "depends_on": [], "consumers": [], "reversible": "full",
            "blast_radius": "user", "takes_effect": "next-session", "contains_secret": False, "checks": [],
            "status": status,
            "ops": [{"kind": "json_set", "file": SETTINGS, "path": ["autoCompactWindow"], "value": 400000}]}


def v2_plan(*items):
    return {"schema": 2, "generated": "g", "window_days": 30, "claude_version": "v", "summary": "s",
            "items": list(items) or [v2_item()]}


def test_load_refuses_plan_outside_plans_dir(tmp_home):
    outside = tmp_home / "plan.json"
    outside.write_text(json.dumps(v2_plan()))
    with pytest.raises(PlanError, match="plans"):
        plan_store.load_plan(str(outside))


def test_load_migrates_v1_and_validates(plan_file):
    v1 = v2_plan()
    v1["schema"] = 1
    for k in ("consumers", "reversible", "blast_radius", "takes_effect", "contains_secret", "checks"):
        v1["items"][0].pop(k)
    v1["items"][0]["verify"] = "look"
    path = plan_file(v1)
    plan, loaded_path = plan_store.load_plan(str(path))
    assert plan["schema"] == 2 and plan["items"][0]["checks"][0]["kind"] == "note"
    assert loaded_path == path


def test_load_reports_invalid_plan(plan_file):
    bad = v2_plan()
    bad["items"][0]["risk"] = "yolo"
    path = plan_file(bad)
    with pytest.raises(PlanError, match="risk"):
        plan_store.load_plan(str(path))


def test_load_default_uses_latest_symlink(plan_file):
    path = plan_file(v2_plan())
    plan_store.point_latest(path)
    plan, loaded = plan_store.load_plan(None)
    assert loaded.resolve() == path.resolve()


def test_save_is_atomic_and_0600(plan_file):
    path = plan_file(v2_plan())
    plan = json.loads(path.read_text())
    plan["items"][0]["status"] = "applied"
    plan_store.save_plan(plan, path)
    assert json.loads(path.read_text())["items"][0]["status"] == "applied"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [p for p in os.listdir(path.parent) if p.endswith(".tmp")] == []


def test_locked_blocks_second_holder(tmp_home):
    with plan_store.locked():
        fd = os.open(plan_store.lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.close(fd)


def test_point_latest_refuses_when_old_plan_has_applied_items(plan_file):
    old = plan_file(v2_plan(v2_item(status="applied")), "old.json")
    plan_store.point_latest(old)
    new = plan_file(v2_plan(), "new.json")
    with pytest.raises(PlanError, match="P1-01"):
        plan_store.point_latest(new)
    assert os.path.realpath(plan_store.latest_path()) == str(old.resolve())


def test_point_latest_force_overrides(plan_file):
    old = plan_file(v2_plan(v2_item(status="applied")), "old.json")
    plan_store.point_latest(old)
    new = plan_file(v2_plan(), "new.json")
    plan_store.point_latest(new, force=True)
    assert os.path.realpath(plan_store.latest_path()) == str(new.resolve())


def test_point_latest_refuses_outside_plans_dir(tmp_home):
    outside = tmp_home / "plan.json"
    outside.write_text(json.dumps(v2_plan()))
    with pytest.raises(PlanError):
        plan_store.point_latest(outside)
