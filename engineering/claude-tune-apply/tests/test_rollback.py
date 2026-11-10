import json
import os
import stat

import pytest

import backup
import tune_ops
from plan_schema import PlanError


def _apply(tmp_home, item_id, op, deps=()):
    """Preview, back up, write; return (plan, item) as the engine would record them."""
    results = tune_ops.preview_item_ops([op])
    bdir = backup.make_backup(item_id, results)
    for r in results:
        tune_ops.write_result(r)
    backup.record_after_hashes(bdir)
    item = {"id": item_id, "status": "applied", "backup": str(bdir), "depends_on": list(deps),
            "files": sorted({r.path for r in results if r.changed})}
    return item


def _plan(*items):
    return {"schema": 2, "items": list(items)}


def test_rollback_refuses_unless_applied(tmp_home):
    item = {"id": "P1-01", "status": "proposed", "depends_on": []}
    with pytest.raises(PlanError, match="applied"):
        backup.rollback_item(_plan(item), item)


def test_rollback_refuses_backup_outside_root(tmp_home):
    item = {"id": "P1-01", "status": "applied", "backup": str(tmp_home / "x"), "depends_on": []}
    with pytest.raises(PlanError, match="not under"):
        backup.rollback_item(_plan(item), item)


def test_rollback_refuses_manifest_path_outside_allowlist(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    item = _apply(tmp_home, "P1-01", {"kind": "file_append", "file": str(p), "content": "y\n"})
    bdir = backup.backup_dir_for(item)
    manifest = json.loads((bdir / "manifest.json").read_text())
    manifest["files"][0]["path"] = str(tmp_home / ".ssh" / "authorized_keys")
    (bdir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PlanError):
        backup.rollback_item(_plan(item), item)


def test_rollback_refuses_on_drift_without_force(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    item = _apply(tmp_home, "P1-01", {"kind": "file_append", "file": str(p), "content": "y\n"})
    p.write_text("x\ny\nuser edit\n")
    with pytest.raises(PlanError, match="--force"):
        backup.rollback_item(_plan(item), item)
    assert p.read_text() == "x\ny\nuser edit\n"


def test_rollback_with_force_restores_and_warns(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    item = _apply(tmp_home, "P1-01", {"kind": "file_append", "file": str(p), "content": "y\n"})
    p.write_text("x\ny\nuser edit\n")
    warnings = backup.rollback_item(_plan(item), item, force=True)
    assert p.read_text() == "x\n" and item["status"] == "rolled_back"
    assert any("edited" in w or "drift" in w for w in warnings)


def test_rollback_restores_mode_0755(tmp_home):
    p = tmp_home / ".claude" / "hooks" / "run.sh"
    p.parent.mkdir()
    p.write_text("#!/bin/sh\n")
    os.chmod(p, 0o755)
    item = _apply(tmp_home, "P1-09", {"kind": "file_append", "file": str(p), "content": "echo\n"})
    backup.rollback_item(_plan(item), item)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o755 and p.read_text() == "#!/bin/sh\n"


def test_rollback_recreates_removed_symlink(tmp_home):
    target = tmp_home / ".agents" / "skills" / "x"
    target.mkdir(parents=True)
    link = tmp_home / ".claude" / "skills" / "x"
    link.parent.mkdir()
    os.symlink("../../.agents/skills/x", link)
    item = _apply(tmp_home, "P3-01", {"kind": "file_remove", "file": str(link)})
    assert not os.path.lexists(link)
    backup.rollback_item(_plan(item), item)
    assert os.path.islink(link) and os.readlink(link) == "../../.agents/skills/x"


def test_rollback_removes_created_file_and_created_parent(tmp_home):
    p = tmp_home / ".claude" / "hooks" / "new.sh"
    item = _apply(tmp_home, "P1-09", {"kind": "file_create", "file": str(p), "content": "x\n"})
    backup.rollback_item(_plan(item), item)
    assert not p.exists() and not p.parent.exists()


def test_rollback_resets_transitive_dependents(tmp_home):
    a = tmp_home / ".claude" / "a.md"
    a.write_text("a\n")
    first = _apply(tmp_home, "P2-02", {"kind": "file_append", "file": str(a), "content": "rule\n"})
    second = {"id": "P5-01", "status": "applied", "depends_on": ["P2-02"], "files": []}
    third = {"id": "P5-02", "status": "done", "depends_on": ["P5-01"]}
    plan = _plan(first, second, third)
    warnings = backup.rollback_item(plan, first)
    assert second["status"] == "proposed" and third["status"] == "proposed"
    assert any("P5-01" in w for w in warnings) and any("P5-02" in w for w in warnings)


def test_second_rollback_refused(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    item = _apply(tmp_home, "P1-01", {"kind": "file_append", "file": str(p), "content": "y\n"})
    backup.rollback_item(_plan(item), item)
    with pytest.raises(PlanError):
        backup.rollback_item(_plan(item), item)


def _tamper(item, **fields):
    bdir = backup.backup_dir_for(item)
    manifest = json.loads((bdir / "manifest.json").read_text())
    manifest["files"][0].update(fields)
    (bdir / "manifest.json").write_text(json.dumps(manifest))


def test_rollback_refuses_link_target_outside_allowlist(tmp_home):
    link = tmp_home / ".claude" / "skills" / "x"
    link.parent.mkdir()
    (tmp_home / ".agents" / "skills" / "x").mkdir(parents=True)
    os.symlink("../../.agents/skills/x", link)
    item = _apply(tmp_home, "P3-01", {"kind": "file_remove", "file": str(link)})
    _tamper(item, link_target="/etc/passwd")
    with pytest.raises(PlanError):
        backup.rollback_item(_plan(item), item)
    assert not os.path.lexists(link)


def test_rollback_refuses_relative_manifest_path(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    item = _apply(tmp_home, "P1-01", {"kind": "file_append", "file": str(p), "content": "y\n"})
    _tamper(item, path=".claude/a.md")
    with pytest.raises(PlanError):
        backup.rollback_item(_plan(item), item)


def test_rollback_refuses_non_int_mode(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    item = _apply(tmp_home, "P1-01", {"kind": "file_append", "file": str(p), "content": "y\n"})
    _tamper(item, mode="755")
    with pytest.raises(PlanError, match="mode"):
        backup.rollback_item(_plan(item), item)
