import hashlib
import json
import os

import pytest

import checks
import runner
import selection
from plan_schema import PlanError


def settings(tmp_home, doc):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text(json.dumps(doc) + "\n")
    return str(p)


def run_one(item_checks, phase="post"):
    results = checks.run_checks({"id": "P1-01", "checks": item_checks}, phase)
    assert len(results) == 1
    return results[0]


def test_json_equals(tmp_home):
    path = settings(tmp_home, {"a": {"b": 1}})
    assert run_one([{"phase": "post", "kind": "json_equals", "file": path, "path": ["a", "b"], "value": 1}]).ok
    assert not run_one([{"phase": "post", "kind": "json_equals", "file": path, "path": ["a", "b"], "value": 2}]).ok


def test_json_absent(tmp_home):
    path = settings(tmp_home, {"a": 1})
    assert run_one([{"phase": "post", "kind": "json_absent", "file": path, "path": ["zzz"]}]).ok
    assert not run_one([{"phase": "post", "kind": "json_absent", "file": path, "path": ["a"]}]).ok


def test_file_contains_and_absent(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("hello\n")
    assert run_one([{"phase": "post", "kind": "file_contains", "file": str(p), "text": "hello"}]).ok
    assert not run_one([{"phase": "post", "kind": "file_contains", "file": str(p), "text": "bye"}]).ok
    assert not run_one([{"phase": "post", "kind": "file_absent", "file": str(p)}]).ok
    assert run_one([{"phase": "post", "kind": "file_absent", "file": str(tmp_home / ".claude" / "none")}]).ok


def test_file_sha256_and_mode(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    os.chmod(p, 0o600)
    good = hashlib.sha256(b"x\n").hexdigest()
    assert run_one([{"phase": "post", "kind": "file_sha256", "file": str(p), "sha256": good}]).ok
    assert not run_one([{"phase": "post", "kind": "file_sha256", "file": str(p), "sha256": "0" * 64}]).ok
    assert run_one([{"phase": "post", "kind": "file_mode", "file": str(p), "mode": 0o600}]).ok
    assert not run_one([{"phase": "post", "kind": "file_mode", "file": str(p), "mode": 0o644}]).ok


def test_cmd_exit_ok_and_not_ok(tmp_home):
    assert run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["test", "-d", str(tmp_home)]}]).ok
    assert not run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["test", "-d", str(tmp_home / "none")]}]).ok


def test_cmd_exit_refuses_non_allowlisted():
    r = run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["rm", "-rf", "/"]}])
    assert not r.ok and "allowlist" in r.detail


def test_cmd_exit_times_out(monkeypatch):
    import plan_schema
    monkeypatch.setattr(plan_schema, "CHECK_CMD_ALLOWLIST", plan_schema.CHECK_CMD_ALLOWLIST + ("sleep",))
    r = run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["sleep", "5"], "timeout_s": 0.2}])
    assert not r.ok and "timed out" in r.detail


def test_note_is_always_ok_and_phase_filter():
    results = checks.run_checks({"id": "x", "checks": [{"phase": "deferred", "kind": "note", "text": "later"},
                                                       {"phase": "post", "kind": "note", "text": "now"}]}, "deferred")
    assert [r.ok for r in results] == [True] and "later" in results[0].detail


def mkitem(id, ops, item_checks, risk="safe", deps=()):
    return {"id": id, "phase": int(id[1]), "title": id, "risk": risk, "why": "w", "evidence": "e",
            "docs": "https://x", "impact": "i", "depends_on": list(deps), "consumers": [], "reversible": "full",
            "blast_radius": "user", "takes_effect": "next-session", "contains_secret": False,
            "checks": item_checks, "status": "proposed", "ops": ops}


def mkplan(*items):
    return {"schema": 2, "generated": "g", "window_days": 30, "claude_version": "v", "summary": "s",
            "items": list(items)}


def test_pre_check_failure_refuses_before_backup(tmp_home, plan_file):
    path = settings(tmp_home, {"a": 1})
    item = mkitem("P1-01", [{"kind": "json_set", "file": path, "path": ["a"], "value": 2}],
                  [{"phase": "pre", "kind": "json_equals", "file": path, "path": ["a"], "value": 999}])
    plan = mkplan(item)
    _, digest = runner.dry_run(plan, [item])
    runner.apply_items(plan, [item], plan_file(plan), expect=digest, confirmed=set())
    assert item["status"] == "failed" and "pre-check" in item["error"]
    assert not (tmp_home / ".claude" / "tune" / "backups").exists()
    assert json.loads(open(path).read()) == {"a": 1}


def test_post_check_failure_rolls_back_item(tmp_home, plan_file):
    path = settings(tmp_home, {"a": 1})
    item = mkitem("P1-01", [{"kind": "json_set", "file": path, "path": ["a"], "value": 2}],
                  [{"phase": "post", "kind": "json_equals", "file": path, "path": ["a"], "value": 3}])
    plan = mkplan(item)
    _, digest = runner.dry_run(plan, [item])
    runner.apply_items(plan, [item], plan_file(plan), expect=digest, confirmed=set())
    assert item["status"] == "failed" and "post-check" in item["error"]
    assert json.loads(open(path).read()) == {"a": 1}


def test_mark_done_runs_post_checks(tmp_home):
    missing = str(tmp_home / ".config" / "claude" / "secrets.env")
    manual = mkitem("P0-02", [{"kind": "manual", "text": "create the file"}],
                    [{"phase": "post", "kind": "file_mode", "file": missing, "mode": 0o600}], risk="manual")
    plan = mkplan(manual)
    with pytest.raises(PlanError, match="post-check"):
        selection.mark_done(plan, ["P0-02"], run_post_checks=checks.require_post)
    assert manual["status"] == "proposed"


def test_cmd_exit_refuses_path_qualified_argv0():
    r = run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["/usr/bin/test", "-d", "/"]}])
    assert not r.ok and "bare" in r.detail


def test_cmd_exit_claude_only_fixed_forms():
    bad = run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["claude", "-p", "hello"]}])
    assert not bad.ok and "form" in bad.detail
    ok_form = run_one([{"phase": "post", "kind": "cmd_exit", "argv": ["claude", "--version"]}])
    assert "form" not in ok_form.detail and "allowlist" not in ok_form.detail


def test_timeout_is_clamped():
    assert checks.timeout_for({"timeout_s": 9999}) == checks.MAX_TIMEOUT_S
    assert checks.timeout_for({"timeout_s": -1}) == checks.DEFAULT_TIMEOUT_S
    assert checks.timeout_for({"timeout_s": "x"}) == checks.DEFAULT_TIMEOUT_S
    assert checks.timeout_for({"timeout_s": 2}) == 2


def test_check_file_outside_allowlist_not_ok(tmp_home):
    r = run_one([{"phase": "post", "kind": "file_contains", "file": "/etc/passwd", "text": "root"}])
    assert not r.ok and "refused" in r.detail


def test_run_checks_turns_exceptions_into_failures(monkeypatch):
    def boom(check):
        raise RuntimeError("kaboom")
    monkeypatch.setitem(checks.RUNNERS, "note", boom)
    r = run_one([{"phase": "post", "kind": "note", "text": "x"}])
    assert not r.ok and "kaboom" in r.detail


def test_deferred_cmd_exit_is_not_executed():
    r = run_one([{"phase": "deferred", "kind": "cmd_exit", "argv": ["test", "-d", "/"]}], phase="deferred")
    assert r.ok and "not run" in r.detail
