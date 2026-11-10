import json
import os
import re
import subprocess
import sys

import pytest

APPLY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "apply.py")


def run(*args, env=None):
    return subprocess.run([sys.executable, APPLY, *args], capture_output=True, text=True, env=env or os.environ.copy())


def settings(tmp_home, doc):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text(json.dumps(doc) + "\n")
    return str(p)


def mkitem(id, ops, risk="safe", deps=(), **over):
    base = {"id": id, "phase": int(id[1]), "title": f"title {id}", "risk": risk, "why": "because", "evidence": "e",
            "docs": "https://x", "impact": "i", "depends_on": list(deps), "consumers": [], "reversible": "full",
            "blast_radius": "user", "takes_effect": "next-session", "contains_secret": False, "checks": [],
            "status": "proposed", "ops": ops}
    base.update(over)
    return base


def mkplan(*items):
    return {"schema": 2, "generated": "g", "window_days": 30, "claude_version": "v", "summary": "s", "items": list(items)}


@pytest.fixture
def two_item_plan(tmp_home, plan_file):
    path = settings(tmp_home, {"cleanupPeriodDays": 3650})
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate it"}], risk="manual")
    safe = mkitem("P6-01", [{"kind": "json_set", "file": path, "path": ["cleanupPeriodDays"], "value": 90}])
    review = mkitem("P0-03", [{"kind": "json_delete", "file": path, "path": ["cleanupPeriodDays"]}], risk="review",
                    deps=["P0-01"], consumers=["nobody"])
    pf = plan_file(mkplan(manual, safe, review))
    import plan_store
    plan_store.point_latest(pf)
    return pf, path


def test_list_without_plan_exits_0(tmp_home):
    r = run("--list")
    assert r.returncode == 0 and "Run /claude-tune first" in r.stdout


def test_rollback_without_plan_exits_1(tmp_home):
    r = run("--rollback", "P1-01")
    assert r.returncode == 1


def test_list_shows_table_with_blocked_by(two_item_plan):
    r = run("--list")
    assert r.returncode == 0 and "blocked-by" in r.stdout and "P0-01" in r.stdout


def test_dry_run_prints_digest(two_item_plan):
    r = run("--dry-run", "P6-01")
    assert r.returncode == 0
    assert re.search(r"digest: [0-9a-f]{16}", r.stdout) and "nothing written" in r.stdout


def test_apply_without_expect_exits_1_with_hint(two_item_plan):
    r = run("P6-01")
    assert r.returncode == 1 and "--dry-run" in r.stdout and "--expect" in r.stdout


def test_apply_safe_item_end_to_end(two_item_plan):
    pf, path = two_item_plan
    digest = re.search(r"digest: ([0-9a-f]{16})", run("--dry-run", "P6-01").stdout).group(1)
    r = run("P6-01", "--expect", digest)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(open(path).read()) == {"cleanupPeriodDays": 90}
    assert json.loads(pf.read_text())["items"][1]["status"] == "applied"
    assert "--rollback P6-01" in r.stdout


def test_apply_review_item_needs_confirmed(two_item_plan):
    run("--done", "P0-01")
    digest = re.search(r"digest: ([0-9a-f]{16})", run("--dry-run", "P0-03").stdout).group(1)
    r = run("P0-03", "--expect", digest)
    assert r.returncode == 1 and "--confirmed" in r.stdout
    r = run("P0-03", "--expect", digest, "--confirmed", "P0-03")
    assert r.returncode == 0, r.stdout


def test_rollback_end_to_end(two_item_plan):
    pf, path = two_item_plan
    digest = re.search(r"digest: ([0-9a-f]{16})", run("--dry-run", "P6-01").stdout).group(1)
    run("P6-01", "--expect", digest)
    r = run("--rollback", "P6-01")
    assert r.returncode == 0 and json.loads(open(path).read()) == {"cleanupPeriodDays": 3650}
    assert json.loads(pf.read_text())["items"][1]["status"] == "rolled_back"


def test_done_multiple_ids_and_unblock_message(two_item_plan, plan_file):
    pf, _ = two_item_plan
    plan = json.loads(pf.read_text())
    plan["items"].append(mkitem("P0-02", [{"kind": "manual", "text": "wire"}], risk="manual"))
    pf.write_text(json.dumps(plan))
    r = run("--done", "P0-01", "P0-02")
    assert r.returncode == 0 and "P0-03" in r.stdout
    statuses = {it["id"]: it["status"] for it in json.loads(pf.read_text())["items"]}
    assert statuses["P0-01"] == "done" and statuses["P0-02"] == "done"


def test_done_review_item_exits_1(two_item_plan):
    r = run("--done", "P0-03")
    assert r.returncode == 1 and "manual" in r.stdout


def test_undone_resets(two_item_plan):
    run("--done", "P0-01")
    r = run("--undone", "P0-01")
    pf, _ = two_item_plan
    assert r.returncode == 0 and json.loads(pf.read_text())["items"][0]["status"] == "proposed"


def test_explain_prints_consumers_and_deps(two_item_plan):
    r = run("--explain", "P0-03")
    assert r.returncode == 0 and "nobody" in r.stdout and "P0-01" in r.stdout and "because" in r.stdout


def test_purge_backup_marks_item(two_item_plan):
    pf, _ = two_item_plan
    digest = re.search(r"digest: ([0-9a-f]{16})", run("--dry-run", "P6-01").stdout).group(1)
    run("P6-01", "--expect", digest)
    bdir = json.loads(pf.read_text())["items"][1]["backup"]
    r = run("--purge-backup", "P6-01")
    assert r.returncode == 0 and not os.path.exists(bdir)
    assert json.loads(pf.read_text())["items"][1]["status"] == "applied-purged"
    assert run("--rollback", "P6-01").returncode == 1


def test_empty_selection_exits_1(two_item_plan):
    r = run("--dry-run", "phase4")
    assert r.returncode == 1 and "no item" in r.stdout


def test_no_sys_exit_outside_main():
    source = open(APPLY, encoding="utf-8").read()
    assert source.count("sys.exit(") == 1 and "sys.exit(main(" in source
    assert len(source.splitlines()) < 300


def test_migrate_rewrites_schema_and_reports_risk_changes(tmp_home, plan_file):
    path = settings(tmp_home, {})
    v1 = mkplan(mkitem("P1-02", [{"kind": "json_set", "file": path, "path": ["statusLine", "command"], "value": "x"}]),
                mkitem("P6-01", [{"kind": "json_set", "file": path, "path": ["cleanupPeriodDays"], "value": 90}], status="applied"))
    v1["schema"] = 1
    for it in v1["items"]:
        for k in ("consumers", "reversible", "blast_radius", "takes_effect", "contains_secret", "checks"):
            it.pop(k)
        it["verify"] = "look"
    pf = plan_file(v1, "v1.json")
    r = run("--migrate", "--plan", str(pf))
    assert r.returncode == 0 and "schema 2" in r.stdout and "P1-02" in r.stdout
    saved = json.loads(pf.read_text())
    assert saved["schema"] == 2 and saved["items"][1]["status"] == "applied"
    assert saved["items"][0]["checks"][0]["kind"] == "note"
