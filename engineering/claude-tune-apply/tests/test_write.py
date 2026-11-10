import os
import stat

import pytest

import tune_ops
from ops_base import OpResult


def test_write_refuses_when_target_changed_after_preview(tmp_home):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text('{"a": 1}\n')
    r = tune_ops.preview({"kind": "json_set", "file": str(p), "path": ["a"], "value": 2})
    p.write_text('{"a": 99}\n')
    with pytest.raises(tune_ops.StaleTargetError):
        tune_ops.write_result(r)
    assert p.read_text() == '{"a": 99}\n'


def test_write_preserves_existing_mode(tmp_home):
    p = tmp_home / ".claude" / "hooks" / "run.sh"
    p.parent.mkdir()
    p.write_text("#!/bin/sh\necho a\n")
    os.chmod(p, 0o755)
    r = tune_ops.preview({"kind": "file_append", "file": str(p), "content": "echo b\n"})
    tune_ops.write_result(r)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o755


def test_write_new_file_is_0600_under_secure_umask(tmp_home):
    tune_ops.secure_umask()
    p = tmp_home / ".claude" / "new.md"
    r = tune_ops.preview({"kind": "file_create", "file": str(p), "content": "x\n"})
    tune_ops.write_result(r)
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_write_does_not_follow_symlink_target(tmp_home):
    target = tmp_home / ".claude" / "real.md"
    target.write_text("keep\n")
    link = tmp_home / ".claude" / "link.md"
    os.symlink(target, link)
    r = OpResult(kind="file_append", path=str(link), before="keep\n", after="keep\nmore\n", changed=True)
    with pytest.raises(tune_ops.StaleTargetError):
        tune_ops.write_result(r)
    assert target.read_text() == "keep\n"


def test_write_leaves_no_temp_file_on_success(tmp_home):
    p = tmp_home / ".claude" / "settings.json"
    p.write_text("{}\n")
    r = tune_ops.preview({"kind": "json_set", "file": str(p), "path": ["a"], "value": 1})
    tune_ops.write_result(r)
    assert sorted(os.listdir(tmp_home / ".claude")) == ["settings.json", "tune"]
