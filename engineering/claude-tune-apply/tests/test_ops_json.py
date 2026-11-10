import json

import tune_ops


def settings(tmp_home, doc=None):
    p = tmp_home / ".claude" / "settings.json"
    if doc is not None:
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return str(p)


def test_json_delete_missing_file_is_unchanged_and_writes_nothing(tmp_home):
    path = settings(tmp_home)
    r = tune_ops.preview({"kind": "json_delete", "file": path, "path": ["env", "X"]})
    assert not r.changed and not r.errors
    tune_ops.write_result(r)
    assert not (tmp_home / ".claude" / "settings.json").exists()


def test_json_delete_empty_file_reports_error(tmp_home):
    path = settings(tmp_home, "   \n")
    r = tune_ops.preview({"kind": "json_delete", "file": path, "path": ["env", "X"]})
    assert r.errors and "JSON" in r.errors[0]


def test_json_set_string_parent_reports_error(tmp_home):
    path = settings(tmp_home, {"env": "oops"})
    r = tune_ops.preview({"kind": "json_set", "file": path, "path": ["env", "X"], "value": 1})
    assert r.errors and not r.changed


def test_json_set_top_level_list_reports_error(tmp_home):
    path = settings(tmp_home, [1, 2])
    r = tune_ops.preview({"kind": "json_set", "file": path, "path": ["a"], "value": 1})
    assert r.errors and not r.changed


def test_json_append_string_values_reports_error(tmp_home):
    path = settings(tmp_home, {"permissions": {"allow": []}})
    r = tune_ops.preview({"kind": "json_append", "file": path, "path": ["permissions", "allow"], "values": "abc"})
    assert r.errors and not r.changed


def test_json_append_adds_only_missing(tmp_home):
    path = settings(tmp_home, {"permissions": {"allow": ["a"]}})
    r = tune_ops.preview({"kind": "json_append", "file": path, "path": ["permissions", "allow"], "values": ["a", "b"]})
    assert json.loads(r.after)["permissions"]["allow"] == ["a", "b"]


def test_json_upsert_replaces_matching_element(tmp_home):
    hooks = [{"matcher": "Bash", "hooks": [{"type": "command", "command": "old"}]},
             {"matcher": "Read", "hooks": []}]
    path = settings(tmp_home, {"hooks": {"PreToolUse": hooks}})
    new = {"matcher": "Bash", "hooks": [{"type": "command", "command": "new"}]}
    r = tune_ops.preview({"kind": "json_upsert", "file": path, "path": ["hooks", "PreToolUse"],
                          "match": {"matcher": "Bash"}, "value": new})
    out = json.loads(r.after)["hooks"]["PreToolUse"]
    assert out == [new, {"matcher": "Read", "hooks": []}]


def test_json_upsert_appends_when_no_match(tmp_home):
    path = settings(tmp_home, {"hooks": {}})
    new = {"matcher": "Bash", "hooks": []}
    r = tune_ops.preview({"kind": "json_upsert", "file": path, "path": ["hooks", "PreToolUse"],
                          "match": {"matcher": "Bash"}, "value": new})
    assert json.loads(r.after)["hooks"]["PreToolUse"] == [new]


def test_expect_mismatch_reports_error(tmp_home):
    path = settings(tmp_home, {"cleanupPeriodDays": 90})
    r = tune_ops.preview({"kind": "json_set", "file": path, "path": ["cleanupPeriodDays"], "value": 30, "expect": 3650})
    assert r.errors and "expect" in r.errors[0] and not r.changed


def test_expect_null_means_absent(tmp_home):
    path = settings(tmp_home, {"a": 1})
    ok = tune_ops.preview({"kind": "json_set", "file": path, "path": ["b"], "value": 1, "expect": None})
    bad = tune_ops.preview({"kind": "json_set", "file": path, "path": ["a"], "value": 2, "expect": None})
    assert ok.changed and not ok.errors
    assert bad.errors


def test_expect_match_proceeds(tmp_home):
    path = settings(tmp_home, {"cleanupPeriodDays": 3650})
    r = tune_ops.preview({"kind": "json_set", "file": path, "path": ["cleanupPeriodDays"], "value": 90, "expect": 3650})
    assert r.changed and not r.errors
