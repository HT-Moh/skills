import copy

import pytest

import plan_lint
import plan_migrate
import plan_risk
import plan_schema

SETTINGS = "~/.claude/settings.json"


def item(**over):
    base = {"id": "P1-01", "phase": 1, "title": "t", "risk": "safe", "why": "w", "evidence": "e",
            "docs": "https://code.claude.com/docs/en/settings-reference.md", "impact": "i",
            "depends_on": [], "consumers": [], "reversible": "full", "blast_radius": "user",
            "takes_effect": "next-session", "contains_secret": False, "checks": [],
            "ops": [{"kind": "json_set", "file": SETTINGS, "path": ["autoCompactWindow"], "value": 400000}]}
    base.update(over)
    return base


def plan(*items):
    return {"schema": 2, "generated": "2026-11-10T13:42:29", "window_days": 30,
            "claude_version": "2.1.322", "summary": "s", "items": list(items)}


def test_validate_accepts_minimal_v2():
    assert plan_schema.validate(plan(item())) == []


def test_validate_rejects_non_dict_item():
    errs = plan_schema.validate(plan("P1-01"))
    assert any("not an object" in e for e in errs)


def test_validate_rejects_id_with_newline():
    errs = plan_schema.validate(plan(item(id="P1-02\n")))
    assert any("id" in e for e in errs)


def test_validate_rejects_string_depends_on():
    errs = plan_schema.validate(plan(item(depends_on="P1-01")))
    assert any("depends_on" in e and "list" in e for e in errs)


def test_validate_detects_cycle():
    a = item(id="P1-01", depends_on=["P1-02"])
    b = item(id="P1-02", depends_on=["P1-01"])
    errs = plan_schema.validate(plan(a, b))
    assert any("cycle" in e for e in errs)


def test_validate_rejects_string_values_for_append():
    op = {"kind": "json_append", "file": SETTINGS, "path": ["permissions", "allow"], "values": "abc"}
    errs = plan_schema.validate(plan(item(ops=[op], risk="review", consumers=["x"])))
    assert any("values" in e and "list" in e for e in errs)


def test_validate_rejects_manual_op_in_review_item():
    ops = [{"kind": "manual", "text": "do it"},
           {"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}]
    errs = plan_schema.validate(plan(item(risk="review", ops=ops)))
    assert any("manual op" in e for e in errs)


def test_validate_requires_unverified_when_docs_empty():
    errs = plan_schema.validate(plan(item(docs="", impact="no marker")))
    assert any("UNVERIFIED" in e for e in errs)
    assert plan_schema.validate(plan(item(docs="", impact="UNVERIFIED: guess"))) == []


def test_validate_rejects_secret_value():
    errs = plan_schema.validate(plan(item(evidence="token sk_live_abcdef0123")))
    assert any("secret" in e for e in errs)


def test_validate_requires_consumers_for_env_delete():
    op = {"kind": "json_delete", "file": SETTINGS, "path": ["env", "X_TOKEN"]}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op], consumers=[])))
    assert any("consumers" in e for e in errs)


@pytest.mark.parametrize("path", [["statusLine", "command"], ["env", "A"], ["hooks", "PreToolUse"],
                                  ["permissions", "allow"], ["mcpServers", "x"]])
def test_effective_risk_floor_for_sensitive_json_roots(path):
    op = {"kind": "json_set", "file": SETTINGS, "path": path, "value": "x"}
    assert plan_risk.effective_risk(item(risk="safe", ops=[op])) == "review"


def test_effective_risk_floor_for_file_remove():
    op = {"kind": "file_remove", "file": "~/.claude/settings.json.bak"}
    assert plan_risk.effective_risk(item(risk="safe", ops=[op])) == "review"


def test_effective_risk_floor_for_claude_md():
    op = {"kind": "file_append", "file": "/repo/CLAUDE.md", "content": "x"}
    assert plan_risk.effective_risk(item(risk="safe", ops=[op])) == "review"


def test_effective_risk_keeps_safe_for_enabledPlugins():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["enabledPlugins", "x@y"], "value": False}
    assert plan_risk.effective_risk(item(risk="safe", ops=[op])) == "safe"


def test_effective_risk_manual_stays_manual():
    assert plan_risk.effective_risk(item(risk="manual", ops=[{"kind": "manual", "text": "x"}])) == "manual"


def test_effective_risk_non_full_reversible_is_review():
    assert plan_risk.effective_risk(item(risk="safe", reversible="setting-only")) == "review"


def test_topo_order_dependency_first_across_phases():
    a = item(id="P2-01", phase=2, depends_on=["P5-01"])
    b = item(id="P5-01", phase=5)
    assert [i["id"] for i in plan_schema.topo_order([a, b])] == ["P5-01", "P2-01"]


def test_topo_order_cycle_raises():
    a = item(id="P1-01", depends_on=["P1-02"])
    b = item(id="P1-02", depends_on=["P1-01"])
    with pytest.raises(plan_schema.PlanError):
        plan_schema.topo_order([a, b])


def test_migrate_v1_sets_schema_2_defaults_and_keeps_status():
    v1 = {"schema": 1, "generated": "g", "window_days": 30, "claude_version": "v", "summary": "s",
          "items": [{"id": "P6-01", "phase": 6, "title": "t", "risk": "review", "why": "w", "evidence": "e",
                     "docs": "https://x", "impact": "i", "depends_on": [], "verify": "x", "status": "applied",
                     "ops": [{"kind": "json_set", "file": SETTINGS, "path": ["cleanupPeriodDays"], "value": 90}]}]}
    out = plan_migrate.migrate_v1(copy.deepcopy(v1))
    it = out["items"][0]
    assert out["schema"] == 2
    assert it["status"] == "applied"
    assert it["checks"] == [{"phase": "deferred", "kind": "note", "text": "x"}]
    assert it["consumers"] == [] and it["reversible"] == "full" and "verify" not in it
    assert plan_schema.validate(out) == []


def test_validate_allows_env_set_without_consumers():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["env", "NEW_FLAG"], "value": "1"}
    assert plan_schema.validate(plan(item(risk="review", ops=[op], consumers=[]))) == []


def test_validate_rejects_env_line_secret_inside_string():
    errs = plan_schema.validate(plan(item(evidence="see GITHUB_TOKEN=abc123 in file")))
    assert any("secret" in e for e in errs)


def test_validate_rejects_literal_under_credential_key():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["env", "X_TOKEN"], "value": "abc"}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("credential key" in e for e in errs)


def test_validate_allows_var_reference_under_credential_key():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["env", "X_TOKEN"], "value": "${X_TOKEN}"}
    assert plan_schema.validate(plan(item(risk="review", ops=[op]))) == []


def test_validate_rejects_nested_literal_under_credential_key():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["mcpServers", "x"],
          "value": {"env": {"API_KEY": "abc"}}}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("credential key" in e for e in errs)


def test_validate_rejects_partial_var_reference():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["env", "X_TOKEN"], "value": "${X}abc"}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("credential key" in e for e in errs)


def test_validate_rejects_secret_in_json_append_values():
    op = {"kind": "json_append", "file": SETTINGS, "path": ["permissions", "allow"], "values": ["sk_live_abcdef0123"]}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op], consumers=["x"])))
    assert any("secret" in e for e in errs)


def test_validate_rejects_literal_in_append_values_under_credential_path():
    op = {"kind": "json_append", "file": SETTINGS, "path": ["env", "X_TOKEN"], "values": ["abc"]}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("credential key" in e for e in errs)


def test_validate_rejects_literal_under_credential_ancestor():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["env", "X_TOKEN"], "value": {"nested": "abc"}}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("credential key" in e for e in errs)


def test_validate_rejects_var_reference_with_default():
    op = {"kind": "json_set", "file": SETTINGS, "path": ["env", "X_TOKEN"], "value": "${X:-abc}"}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("credential key" in e for e in errs)


@pytest.mark.parametrize("mode", [0o777, 0o666, 0o4755, "700"])
def test_validate_rejects_unsafe_or_non_int_mode(mode):
    op = {"kind": "file_create", "file": "~/.claude/hooks/x.sh", "content": "x", "mode": mode}
    errs = plan_schema.validate(plan(item(risk="review", ops=[op])))
    assert any("mode" in e for e in errs)


def test_validate_accepts_owner_only_mode():
    op = {"kind": "file_create", "file": "~/.claude/hooks/x.sh", "content": "x", "mode": 0o700}
    assert plan_schema.validate(plan(item(risk="review", ops=[op]))) == []


def test_effective_risk_unchanged_by_cmd_exit_check():
    it = item(risk="safe", checks=[{"phase": "post", "kind": "cmd_exit", "argv": ["test", "-d", "/"]}])
    assert plan_risk.effective_risk(it) == "safe"  # cmd_exit is shown to the user, never executed


def test_validate_rejects_cmd_exit_with_path_argv0_or_bad_timeout():
    bad_argv = item(checks=[{"phase": "post", "kind": "cmd_exit", "argv": ["/usr/bin/test", "-d", "/"]}])
    bad_timeout = item(checks=[{"phase": "post", "kind": "cmd_exit", "argv": ["test", "-d", "/"], "timeout_s": 999}])
    assert any("argv" in e for e in plan_schema.validate(plan(bad_argv)))
    assert any("timeout" in e for e in plan_schema.validate(plan(bad_timeout)))


@pytest.mark.parametrize("op", [
    {"kind": "file_append", "file": "/repo/.claude/settings.json", "content": "x"},
    {"kind": "file_create", "file": "/repo/.mcp.json", "content": "{}"},
    {"kind": "file_append", "file": "~/.claude/rules/workflow.md", "content": "x"},
    {"kind": "file_create", "file": "~/.claude/agents/x.md", "content": "x"},
    {"kind": "file_create", "file": "~/.claude/commands/x.md", "content": "x"},
    {"kind": "file_create", "file": "~/.claude/notes/run.sh", "content": "x", "mode": 0o700},
])
def test_effective_risk_floor_for_instruction_and_executable_files(op):
    assert plan_risk.effective_risk(item(risk="safe", ops=[op])) == "review"


def test_validate_rejects_cmd_exit_outside_deferred():
    it = item(checks=[{"phase": "post", "kind": "cmd_exit", "argv": ["test", "-d", "/"]}])
    assert any("deferred" in e for e in plan_schema.validate(plan(it)))
    ok = item(checks=[{"phase": "deferred", "kind": "cmd_exit", "argv": ["test", "-d", "/"]}])
    assert plan_schema.validate(plan(ok)) == []


def test_validate_accepts_artifact_page_url():
    p = plan(item())
    p["page_url"] = "https://claude.ai/artifact/F4MKKZG56qTCCZEfLzMGXt"
    assert plan_schema.validate(p) == []


def test_validate_rejects_page_url_outside_claude_ai():
    p = plan(item())
    p["page_url"] = "https://example.com/artifact/x"
    assert any("page_url" in e for e in plan_schema.validate(p))


def test_warnings_flag_text_that_relies_on_a_dependent_item():
    first = item(id="P0-01", risk="manual", ops=[{"kind": "manual", "text": "put the new values in the file created by P0-02"}])
    second = item(id="P0-02", risk="manual", depends_on=["P0-01"], ops=[{"kind": "manual", "text": "create the file"}])
    warnings = plan_lint.warnings(plan(first, second))
    assert len(warnings) == 1 and "P0-01" in warnings[0] and "P0-02" in warnings[0]


def test_warnings_stay_silent_when_the_mentioned_item_has_no_dependency_back():
    first = item(id="P0-01", risk="manual", ops=[{"kind": "manual", "text": "then P0-03 deletes the literals"}])
    third = item(id="P0-03", ops=[{"kind": "json_delete", "file": SETTINGS, "path": ["env", "X"]}], risk="review")
    assert plan_lint.warnings(plan(first, third)) == []


def manual_with_steps(steps):
    return item(id="P0-01", risk="manual", ops=[{"kind": "manual", "text": "rotate the key", "steps": steps}])


def test_validate_accepts_manual_steps_with_code_and_lang():
    steps = [{"text": "Create the file", "code": "install -m 600 /dev/null ~/.config/claude/secrets.env", "lang": "bash"},
             {"text": "Restart the shell"}]
    assert plan_schema.validate(plan(manual_with_steps(steps))) == []


def test_validate_rejects_step_without_text():
    errs = plan_schema.validate(plan(manual_with_steps([{"code": "ls"}])))
    assert any("steps[0]" in e and "text" in e for e in errs)


def test_validate_rejects_steps_that_are_not_a_list():
    errs = plan_schema.validate(plan(manual_with_steps("do it")))
    assert any("steps" in e and "list" in e for e in errs)


def test_validate_rejects_odd_step_lang():
    errs = plan_schema.validate(plan(manual_with_steps([{"text": "x", "code": "y", "lang": "Bash Shell"}])))
    assert any("lang" in e for e in errs)
