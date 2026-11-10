import consumers


def test_find_consumers_names_skill_file_not_content(tmp_home):
    skill = tmp_home / ".agents" / "skills" / "browserless"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text('curl -sf "$BROWSERLESS_URL/content?token=$BROWSERLESS_TOKEN"\n')
    found = consumers.find_consumers(["BROWSERLESS_TOKEN"])
    assert found == [f"{skill / 'SKILL.md'}: BROWSERLESS_TOKEN"]
    assert all("curl" not in line for line in found)


def test_find_consumers_reports_claude_json_key_names_only(tmp_home):
    (tmp_home / ".claude.json").write_text('{"mcpServers": {"fc": {"env": {"FIRECRAWL_TOKEN": "abc"}}}}')
    found = consumers.find_consumers(["FIRECRAWL_TOKEN"])
    assert found == [f"{tmp_home / '.claude.json'}: FIRECRAWL_TOKEN"]


def test_find_consumers_empty_when_nothing_reads_the_name(tmp_home):
    assert consumers.find_consumers(["QDRANT_TOKEN"]) == []


def test_find_consumers_checks_crontab(tmp_home, monkeypatch):
    monkeypatch.setattr(consumers, "_crontab", lambda: "0 * * * * X_TOKEN=1 run.sh\n")
    assert consumers.find_consumers(["X_TOKEN"]) == ["crontab: X_TOKEN"]


def test_key_names_touched_env_delete():
    item = {"ops": [{"kind": "json_delete", "file": "~/.claude/settings.json", "path": ["env", "BROWSERLESS_TOKEN"]},
                    {"kind": "json_set", "file": "~/.claude/settings.json", "path": ["autoCompactWindow"], "value": 1},
                    {"kind": "json_append", "file": "~/.claude/settings.json", "path": ["permissions", "allow"], "values": []}]}
    assert consumers.key_names_touched(item) == ["BROWSERLESS_TOKEN", "allow"]
