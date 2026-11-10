import hashlib
import os
import stat

import tune_ops


def claude(tmp_home, name, text=None):
    p = tmp_home / ".claude" / name
    if text is not None:
        p.write_text(text)
    return str(p)


def test_file_replace_twice_when_new_contains_old(tmp_home):
    path = claude(tmp_home, "r.py", 'cmd = ["json"]\n')
    op = {"kind": "file_replace", "file": path, "old": '"json"]', "new": '"json", "--flag"]'}
    first = tune_ops.preview(op)
    assert first.changed
    tune_ops.write_result(first)
    second = tune_ops.preview(op)
    assert not second.changed and not second.errors


def test_file_replace_deletion_twice(tmp_home):
    path = claude(tmp_home, "a.md", "keep\n## RULES\n\n@RULES.md\n")
    op = {"kind": "file_replace", "file": path, "old": "## RULES\n\n@RULES.md\n", "new": ""}
    tune_ops.write_result(tune_ops.preview(op))
    second = tune_ops.preview(op)
    assert not second.changed and not second.errors


def test_file_append_line_match_not_substring(tmp_home):
    path = claude(tmp_home, "rc", "alias x=10\n")
    r = tune_ops.preview({"kind": "file_append", "file": path, "content": "alias x=1\n"})
    assert r.changed


def test_file_append_already_present_by_lines(tmp_home):
    path = claude(tmp_home, "rc", "a\nb\n")
    r = tune_ops.preview({"kind": "file_append", "file": path, "content": "b\n"})
    assert not r.changed and not r.errors


def test_file_append_empty_content_is_error(tmp_home):
    path = claude(tmp_home, "rc", "a\n")
    r = tune_ops.preview({"kind": "file_append", "file": path, "content": "  \n"})
    assert r.errors


def test_file_create_mode_applied_on_write(tmp_home):
    path = claude(tmp_home, "hooks/guard.sh")
    r = tune_ops.preview({"kind": "file_create", "file": path, "content": "#!/bin/sh\n", "mode": 0o700})
    tune_ops.write_result(r)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o700


def test_file_remove_diff_prints_summary_only(tmp_home):
    path = claude(tmp_home, "settings.json.bak", '{"env": {"TOKEN": "abc"}}\n')
    r = tune_ops.preview({"kind": "file_remove", "file": path})
    d = r.diff()
    assert "abc" not in d and "1 line" in d and "sha256" in d


def test_file_remove_symlink_records_link_target(tmp_home):
    target = claude(tmp_home, "real.txt", "x")
    link = str(tmp_home / ".claude" / "link.txt")
    os.symlink(target, link)
    r = tune_ops.preview({"kind": "file_remove", "file": link})
    assert r.changed and r.symlink_target == target
    tune_ops.write_result(r)
    assert not os.path.lexists(link) and os.path.exists(target)


def test_file_remove_dangling_symlink_changes(tmp_home):
    link = str(tmp_home / ".claude" / "skills" / "gone")
    os.makedirs(os.path.dirname(link))
    os.symlink("/nonexistent/target", link)
    r = tune_ops.preview({"kind": "file_remove", "file": link})
    assert r.changed and not r.errors
    tune_ops.write_result(r)
    assert not os.path.lexists(link)


def test_file_op_on_symlink_target_is_error(tmp_home):
    target = claude(tmp_home, "real.json", "{}")
    link = str(tmp_home / ".claude" / "alias.json")
    os.symlink(target, link)
    r = tune_ops.preview({"kind": "file_append", "file": link, "content": "x\n"})
    assert r.errors and "symlink" in r.errors[0]


def test_file_op_on_directory_is_error(tmp_home):
    r = tune_ops.preview({"kind": "file_remove", "file": str(tmp_home / ".claude")})
    assert r.errors and "directory" in r.errors[0]


def test_symlink_missing_target_is_error(tmp_home):
    link = str(tmp_home / ".claude" / "skills" / "x")
    r = tune_ops.preview({"kind": "symlink", "link": link, "target": "../../.agents/skills/x"})
    assert r.errors and "target" in r.errors[0]


def test_symlink_target_outside_allowlist_is_error(tmp_home):
    link = str(tmp_home / ".claude" / "skills" / "x")
    r = tune_ops.preview({"kind": "symlink", "link": link, "target": "/etc"})
    assert r.errors


def test_symlink_equivalent_target_unchanged(tmp_home):
    target_dir = tmp_home / ".agents" / "skills" / "x"
    target_dir.mkdir(parents=True)
    link = tmp_home / ".claude" / "skills" / "x"
    link.parent.mkdir()
    os.symlink(str(target_dir), link)
    r = tune_ops.preview({"kind": "symlink", "link": str(link), "target": "../../.agents/skills/x"})
    assert not r.changed and not r.errors


def test_sha256_precondition_mismatch_is_error(tmp_home):
    path = claude(tmp_home, "f.md", "now\n")
    stale = hashlib.sha256(b"then\n").hexdigest()
    r = tune_ops.preview({"kind": "file_append", "file": path, "content": "x\n", "sha256": stale})
    assert r.errors and "sha256" in r.errors[0]


def test_file_replace_not_fooled_by_new_text_elsewhere(tmp_home):
    path = claude(tmp_home, "agent.md", "model: sonnet\n# opus is for design\n")
    r = tune_ops.preview({"kind": "file_replace", "file": path, "old": "model: sonnet", "new": "model: opus"})
    assert r.changed and not r.errors and r.after.startswith("model: opus\n")
