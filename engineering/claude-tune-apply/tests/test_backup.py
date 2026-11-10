import json
import os
import stat
from pathlib import Path

import pytest

import backup
import tune_ops
from plan_schema import PlanError


def _result(path, before, after, kind="file_append"):
    return tune_ops.OpResult(kind=kind, path=str(path), before=before, after=after, changed=True)


def test_backup_dir_unique_within_same_second(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    r = _result(p, "x\n", "x\ny\n")
    a = backup.make_backup("P1-01", [r])
    b = backup.make_backup("P1-01", [r])
    assert a != b and a.is_dir() and b.is_dir()


def test_manifest_records_mode_and_link_target(tmp_home):
    script = tmp_home / ".claude" / "hooks" / "run.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    os.chmod(script, 0o755)
    link = tmp_home / ".claude" / "skills" / "x"
    link.parent.mkdir()
    os.symlink("../../.agents/skills/x", link)
    r_file = _result(script, "#!/bin/sh\n", "#!/bin/sh\necho\n")
    r_link = tune_ops.OpResult(kind="file_remove", path=str(link), after=None, changed=True,
                               symlink_target="../../.agents/skills/x", summary_only=True)
    bdir = backup.make_backup("P3-01", [r_file, r_link])
    manifest = json.loads((bdir / "manifest.json").read_text())
    by_path = {f["path"]: f for f in manifest["files"]}
    assert by_path[str(script)]["mode"] == 0o755
    assert by_path[str(link)]["link_target"] == "../../.agents/skills/x"
    assert by_path[str(link)]["saved_as"] == ""


def test_manifest_dedupes_same_path(tmp_home):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text("{}\n")
    r1 = _result(p, "{}\n", '{"a": 1}\n', kind="json_set")
    r2 = _result(p, '{"a": 1}\n', '{"a": 1, "b": 2}\n', kind="json_set")
    bdir = backup.make_backup("P1-01", [r1, r2])
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert len(manifest["files"]) == 1


def test_contains_secret_flag_set_when_saved_copy_has_token(tmp_home):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text('{"env": {"X_TOKEN": "abc123"}}\n')
    bdir = backup.make_backup("P0-03", [_result(p, p.read_text(), "{}\n", kind="json_delete")])
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["contains_secret"] is True


def test_backup_dir_for_rejects_path_outside_root(tmp_home):
    with pytest.raises(PlanError):
        backup.backup_dir_for({"id": "P1-01", "backup": str(tmp_home / "elsewhere")})


def test_backup_dir_for_rejects_saved_as_with_slash(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    bdir = backup.make_backup("P1-01", [_result(p, "x\n", "y\n")])
    manifest = json.loads((bdir / "manifest.json").read_text())
    manifest["files"][0]["saved_as"] = "../../evil"
    (bdir / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(PlanError):
        backup.load_manifest(bdir)


def test_tune_tree_created_0700(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    bdir = backup.make_backup("P1-01", [_result(p, "x\n", "y\n")])
    for d in (bdir, bdir.parent, bdir.parent.parent):
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o700, d
    assert stat.S_IMODE(os.stat(bdir / "manifest.json").st_mode) == 0o600


def test_record_after_hashes_fills_sha256(tmp_home):
    p = tmp_home / ".claude" / "a.md"
    p.write_text("x\n")
    r = _result(p, "x\n", "y\n")
    bdir = backup.make_backup("P1-01", [r])
    tune_ops.write_result(r)
    backup.record_after_hashes(bdir)
    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["files"][0]["sha256_after"] == backup.sha256_file(Path(p))
