import report
import runner
import tune_ops

SETTINGS = "~/.claude/settings.json"


def mkitem(id, ops, risk="safe", deps=(), status="proposed", **over):
    base = {"id": id, "phase": int(id[1]), "title": f"title {id}", "risk": risk, "why": "because",
            "evidence": "42 files, scan.json", "docs": "https://code.claude.com/docs/en/x.md", "impact": "big",
            "depends_on": list(deps), "consumers": [], "reversible": "full", "blast_radius": "user",
            "takes_effect": "next-session", "contains_secret": False,
            "checks": [{"phase": "deferred", "kind": "note", "text": "look at /cost"}], "status": status, "ops": ops}
    base.update(over)
    return base


def mkplan(*items):
    return {"schema": 2, "generated": "2026-11-10T13:42:29", "window_days": 30, "claude_version": "v",
            "summary": "s", "items": list(items)}


def test_explain_lists_dependency_statuses():
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate"}], risk="manual", status="done")
    other = mkitem("P0-02", [{"kind": "manual", "text": "wire"}], risk="manual")
    dep = mkitem("P0-03", [{"kind": "json_delete", "file": SETTINGS, "path": ["env", "X_TOKEN"]}],
                 risk="review", deps=["P0-01", "P0-02"], consumers=["~/.agents/skills/browserless/SKILL.md"])
    text = report.explain(dep, mkplan(manual, other, dep))
    assert "P0-01" in text and "done" in text and "P0-02" in text and "proposed" in text
    assert "browserless" in text and "because" in text and "look at /cost" in text and "review" in text


def test_explain_names_the_risk_floor_reason():
    item = mkitem("P1-02", [{"kind": "json_set", "file": SETTINGS, "path": ["statusLine", "command"], "value": "x"}])
    text = report.explain(item, mkplan(item))
    assert "declared safe" in text and "statusLine" in text


def test_show_preview_warns_exec_for_hooks(tmp_home):
    path = str(tmp_home / ".claude" / "settings.json")
    (tmp_home / ".claude" / "settings.json").write_text("{}\n")
    item = mkitem("P1-09", [{"kind": "json_set", "file": path, "path": ["hooks", "PreToolUse"], "value": []}])
    previews, _ = runner.dry_run(mkplan(item), [item])
    text = report.show_preview(previews[0], item, mkplan(item))
    assert "WARNING EXEC" in text


def test_show_preview_warns_permission_and_names_removed_entries(tmp_home):
    path = str(tmp_home / ".claude" / "settings.json")
    (tmp_home / ".claude" / "settings.json").write_text('{"permissions": {"allow": ["Bash(ls *)", "Bash(rm *)"]}}\n')
    item = mkitem("P1-08", [{"kind": "json_set", "file": path, "path": ["permissions", "allow"], "value": ["Bash(ls *)"]}],
                  risk="review", consumers=["none"])
    previews, _ = runner.dry_run(mkplan(item), [item])
    text = report.show_preview(previews[0], item, mkplan(item))
    assert "WARNING PERMISSION" in text and "Bash(rm *)" in text


def test_show_preview_lists_blockers_and_consumers(tmp_home):
    path = str(tmp_home / ".claude" / "settings.json")
    (tmp_home / ".claude" / "settings.json").write_text('{"env": {"X_TOKEN": "v"}}\n')
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate"}], risk="manual")
    dep = mkitem("P0-03", [{"kind": "json_delete", "file": path, "path": ["env", "X_TOKEN"]}], risk="review",
                 deps=["P0-01"], consumers=["skill browserless"])
    previews, _ = runner.dry_run(mkplan(manual, dep), [manual, dep])
    text = report.show_preview(previews[1], dep, mkplan(manual, dep))
    assert "blocked by P0-01" in text and "skill browserless" in text and '"v"' not in text


def test_list_table_has_blocked_by_and_next():
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate"}], risk="manual")
    dep = mkitem("P0-03", [{"kind": "json_delete", "file": SETTINGS, "path": ["env", "X"]}], risk="review", deps=["P0-01"])
    done = mkitem("P1-01", [{"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}], status="applied")
    text = report.list_table(mkplan(manual, dep, done))
    assert "blocked-by" in text and "P0-01" in text.split("P0-03")[1].splitlines()[0]
    assert "Next:" in text and "--done P0-01" in text


def test_all_output_is_redacted():
    item = mkitem("P0-01", [{"kind": "manual", "text": "the old key was sk_live_abcdef0123"}], risk="manual")
    assert "sk_live_abcdef0123" not in report.explain(item, mkplan(item))
    r = tune_ops.OpResult(kind="manual", manual_text="sk_live_abcdef0123", changed=False)
    assert "sk_live_abcdef0123" not in report.show_preview(runner.Preview("P0-01", [r]), item, mkplan(item))


def test_show_preview_lists_every_check(tmp_home):
    path = str(tmp_home / ".claude" / "settings.json")
    (tmp_home / ".claude" / "settings.json").write_text("{}\n")
    item = mkitem("P1-01", [{"kind": "json_set", "file": path, "path": ["a"], "value": 1}],
                  checks=[{"phase": "post", "kind": "json_equals", "file": path, "path": ["a"], "value": 1},
                          {"phase": "deferred", "kind": "cmd_exit", "argv": ["claude", "--version"]}])
    previews, _ = runner.dry_run(mkplan(item), [item])
    text = report.show_preview(previews[0], item, mkplan(item))
    assert "checks:" in text and "post: json_equals" in text and "claude --version" in text


def test_list_table_shows_page_url_when_recorded():
    plan = mkplan(mkitem("P1-01", [{"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}]))
    assert "page:" not in report.list_table(plan)
    plan["page_url"] = "https://claude.ai/artifact/F4MKKZG56qTCCZEfLzMGXt"
    assert "page: https://claude.ai/artifact/F4MKKZG56qTCCZEfLzMGXt" in report.list_table(plan)


def test_explain_prints_manual_steps_with_indented_code():
    steps = [{"text": "Create the file", "code": "install -m 600 /dev/null ~/.config/claude/secrets.env"},
             {"text": "Restart the shell"}]
    manual = mkitem("P0-02", [{"kind": "manual", "text": "one secrets file", "steps": steps}], risk="manual")
    out = report.explain(manual, mkplan(manual))
    assert "steps:\n  1. Create the file\n     install -m 600 /dev/null ~/.config/claude/secrets.env\n  2. Restart the shell" in out


def test_explain_prints_plain_manual_text_when_no_steps():
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate it"}], risk="manual")
    assert "steps:\n  - rotate it" in report.explain(manual, mkplan(manual))
