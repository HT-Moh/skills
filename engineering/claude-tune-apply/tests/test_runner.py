import json
import os

import pytest

import runner
from plan_schema import PlanError


def mkitem(id, ops, risk="safe", deps=(), status="proposed"):
    return {"id": id, "phase": int(id[1]), "title": id, "risk": risk, "why": "w", "evidence": "e",
            "docs": "https://x", "impact": "i", "depends_on": list(deps), "consumers": [], "reversible": "full",
            "blast_radius": "user", "takes_effect": "next-session", "contains_secret": False, "checks": [],
            "status": status, "ops": ops}


def mkplan(*items):
    return {"schema": 2, "generated": "g", "window_days": 30, "claude_version": "v", "summary": "s",
            "items": list(items)}


def settings(tmp_home, doc):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text(json.dumps(doc) + "\n")
    return str(p)


def jset(path, key, value):
    return {"kind": "json_set", "file": path, "path": [key], "value": value}


def test_dry_run_chains_overlay_between_items(tmp_home):
    path = settings(tmp_home, {})
    a = mkitem("P1-01", [jset(path, "a", 1)])
    b = mkitem("P1-02", [jset(path, "b", 2)])
    previews, digest = runner.dry_run(mkplan(a, b), [a, b])
    second = previews[1].results[0]
    assert json.loads(second.before) == {"a": 1}
    assert len(digest) == 16


def test_digest_stable_for_same_state(tmp_home):
    path = settings(tmp_home, {})
    a = mkitem("P1-01", [jset(path, "a", 1)])
    _, d1 = runner.dry_run(mkplan(a), [a])
    _, d2 = runner.dry_run(mkplan(a), [a])
    assert d1 == d2


def test_dry_run_reports_blockers_for_manual_dependency(tmp_home):
    path = settings(tmp_home, {})
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate"}], risk="manual")
    dep = mkitem("P0-03", [jset(path, "a", 1)], risk="review", deps=["P0-01"])
    previews, _ = runner.dry_run(mkplan(manual, dep), [manual, dep])
    assert previews[1].blockers == ["P0-01"]


def test_apply_refuses_on_digest_mismatch_after_external_edit(tmp_home, plan_file):
    path = settings(tmp_home, {})
    a = mkitem("P1-01", [jset(path, "a", 1)])
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    settings(tmp_home, {"user": "edit"})
    with pytest.raises(PlanError, match="dry run"):
        runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed=set())
    assert json.loads(open(path).read()) == {"user": "edit"}


def test_apply_refuses_unconfirmed_review_item(tmp_home, plan_file):
    path = settings(tmp_home, {"env": {}})
    a = mkitem("P1-01", [jset(path, "cleanupPeriodDays", 90)], risk="review")
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    with pytest.raises(PlanError, match="--confirmed"):
        runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed=set())


def test_apply_refuses_effective_review_even_if_declared_safe(tmp_home, plan_file):
    path = settings(tmp_home, {})
    a = mkitem("P1-02", [{"kind": "json_set", "file": path, "path": ["statusLine", "command"], "value": "x"}])
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    with pytest.raises(PlanError, match="--confirmed"):
        runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed=set())


def test_apply_refuses_blocked_item(tmp_home, plan_file):
    path = settings(tmp_home, {})
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate"}], risk="manual")
    dep = mkitem("P0-03", [jset(path, "a", 1)], risk="review", deps=["P0-01"])
    plan = mkplan(manual, dep)
    _, digest = runner.dry_run(plan, [manual, dep])
    with pytest.raises(PlanError, match="P0-01"):
        runner.apply_items(plan, [manual, dep], plan_file(plan), expect=digest, confirmed={"P0-03"})
    assert json.loads(open(path).read()) == {}


def test_apply_saves_plan_after_each_item_and_marks_failure(tmp_home, plan_file):
    path = settings(tmp_home, {})
    good = mkitem("P1-01", [jset(path, "a", 1)])
    bad = mkitem("P1-02", [{"kind": "file_append", "file": str(tmp_home / ".claude" / "sub"), "content": "x\n"}])
    (tmp_home / ".claude" / "sub").mkdir()
    plan = mkplan(good, bad)
    _, digest = runner.dry_run(plan, [good, bad])
    pf = plan_file(plan)
    runner.apply_items(plan, [good, bad], pf, expect=digest, confirmed=set())
    saved = json.loads(pf.read_text())
    status = {it["id"]: it["status"] for it in saved["items"]}
    assert status == {"P1-01": "applied", "P1-02": "failed"}
    assert os.path.isdir(saved["items"][0]["backup"])


def test_failed_item_is_restored(tmp_home, plan_file, monkeypatch):
    path = settings(tmp_home, {"keep": True})
    a = mkitem("P1-01", [jset(path, "a", 1), jset(path, "b", 2)])
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    calls = {"n": 0}
    real_write = runner.tune_ops.write_result

    def flaky(r):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        real_write(r)
    monkeypatch.setattr(runner.tune_ops, "write_result", flaky)
    runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed=set())
    assert a["status"] == "failed" and "disk full" in a["error"]
    assert json.loads(open(path).read()) == {"keep": True}


def test_manual_plus_file_ops_ends_needs_user(tmp_home, plan_file):
    path = settings(tmp_home, {})
    a = mkitem("P1-01", [jset(path, "a", 1), {"kind": "manual", "text": "then restart"}], risk="review")
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed={"P1-01"})
    assert a["status"] == "needs_user" and json.loads(open(path).read()) == {"a": 1}


def test_applied_item_records_backup_files_and_time(tmp_home, plan_file):
    path = settings(tmp_home, {})
    a = mkitem("P1-01", [jset(path, "a", 1)])
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed=set())
    assert a["status"] == "applied" and a["files"] == [path] and a["applied_at"] and os.path.isdir(a["backup"])


def test_secret_backup_warning_names_purge_command(tmp_home, plan_file):
    path = settings(tmp_home, {"env": {"X_TOKEN": "abc123"}})
    a = mkitem("P0-03", [{"kind": "json_delete", "file": path, "path": ["env", "X_TOKEN"]}], risk="review")
    a["consumers"] = ["skill x"]
    plan = mkplan(a)
    _, digest = runner.dry_run(plan, [a])
    lines = runner.apply_items(plan, [a], plan_file(plan), expect=digest, confirmed={"P0-03"})
    assert any("--purge-backup P0-03" in line for line in lines)
    assert all("abc123" not in line for line in lines)
