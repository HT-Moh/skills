import json
import os
import stat

import pytest

import skill_inventory

SECRET = "Bearer sk_live_abcdefghijklmnop1234"


def _skill(dir_path, name, description, extra=""):
    dir_path.mkdir(parents=True)
    (dir_path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n# body\n")


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    claude = home / ".claude"
    _skill(home / ".agents" / "skills" / "linked", "linked", 'Use when the user wants "competitor analysis" or keyword research')
    (claude / "skills").mkdir(parents=True)
    os.symlink("../../.agents/skills/linked", claude / "skills" / "linked")
    _skill(claude / "skills" / "manual-only", "manual-only", "Deploy the app", "disable-model-invocation: true\n")
    _skill(claude / "skills" / "turned-off", "turned-off", "Write a cover letter")
    cache = claude / "plugins" / "cache" / "mk"
    _skill(cache / "plug-on" / "1.0.0" / "skills" / "pskill", "pskill", "Review a pull request for bugs")
    _skill(cache / "plug-off" / "1.0.0" / "skills" / "offskill", "offskill", "Generate invoices")
    (cache / "plug-on" / "1.0.0" / "agents").mkdir()
    (cache / "plug-on" / "1.0.0" / "agents" / "reviewer.md").write_text("---\nname: reviewer\n---\n")
    (cache / "plug-on" / "1.0.0" / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"pserver": {"type": "http", "url": "https://p.example", "headers": {"Authorization": SECRET}}}}))
    (claude / "settings.json").write_text(json.dumps({
        "enabledPlugins": {"plug-on@mk": True, "plug-off@mk": False},
        "skillOverrides": {"turned-off": "off"},
    }))
    (claude / "agents").mkdir()
    (claude / "agents" / "my-agent.md").write_text("---\nname: my-agent\n---\n")
    repo = tmp_path / "repo"
    _skill(repo / ".claude" / "skills" / "proj-skill", "proj-skill", "Run the release checklist")
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"localdb": {"command": "db", "env": {"DB_TOKEN": SECRET}}}}))
    (home / ".claude.json").write_text(json.dumps({
        "mcpServers": {"firecrawl": {"type": "http", "url": "https://fc.example", "headers": {"Authorization": SECRET}}},
        "projects": {str(repo): {"mcpServers": {"github": {"type": "http", "url": "https://gh.example"}}},
                     "/elsewhere": {"mcpServers": {"ignored": {"type": "http", "url": "https://x"}}}},
    }))
    return home, repo


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_user_skill_symlink_keeps_link_name_and_resolves_once(fake_home):
    home, repo = fake_home
    skills = _by_name(skill_inventory.build_inventory(str(home), [str(repo)])["skills"])
    assert skills["linked"]["source"] == "user"
    assert skills["linked"]["path"].endswith(".agents/skills/linked/SKILL.md")
    assert sum(1 for r in skills.values() if r["path"] == skills["linked"]["path"]) == 1


def test_disabled_plugin_skill_excluded_enabled_included(fake_home):
    home, repo = fake_home
    skills = _by_name(skill_inventory.build_inventory(str(home), [str(repo)])["skills"])
    assert "offskill" not in skills
    assert skills["pskill"]["source"] == "plugin:plug-on"


def test_model_invoked_false_for_frontmatter_and_skill_override(fake_home):
    home, repo = fake_home
    skills = _by_name(skill_inventory.build_inventory(str(home), [str(repo)])["skills"])
    assert skills["manual-only"]["model_invoked"] is False
    assert skills["turned-off"]["model_invoked"] is False
    assert skills["linked"]["model_invoked"] is True


def test_project_skill_and_mcp_sources(fake_home):
    home, repo = fake_home
    inv = skill_inventory.build_inventory(str(home), [str(repo)])
    assert _by_name(inv["skills"])["proj-skill"]["source"] == "project"
    servers = {s["name"]: s["source"] for s in inv["mcp_servers"]}
    assert servers == {"firecrawl": "user", "github": "project-local", "localdb": "project",
                       "plugin_plug-on_pserver": "plugin:plug-on"}


def test_agents_listed_and_totals(fake_home):
    home, repo = fake_home
    inv = skill_inventory.build_inventory(str(home), [str(repo)])
    assert sorted(a["name"] for a in inv["agents"]) == ["my-agent", "reviewer"]
    assert inv["totals"] == {"skills": 5, "skills_model_invoked": 3, "mcp_servers": 4, "agents": 2, "skill_overrides": 1}


def test_output_file_owner_only_and_free_of_secret_values(fake_home, tmp_path):
    home, repo = fake_home
    out = tmp_path / "inventory.json"
    skill_inventory.write_inventory(skill_inventory.build_inventory(str(home), [str(repo)]), str(out))
    text = out.read_text()
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    assert "sk_live" not in text and "Bearer" not in text and "fc.example" not in text and "DB_TOKEN" not in text


def test_terms_words_and_quoted_phrases():
    terms = skill_inventory.terms_of('Use when the user wants "competitor analysis" or mentions keyword research.')
    assert terms[0] == "competitor analysis"
    assert {"competitor", "analysis", "keyword", "research"} <= set(terms)
    assert not {"when", "user", "wants", "mentions"} & set(terms)


def test_terms_deduped_and_capped_at_40():
    description = " ".join(f"word{i:02d}" for i in range(60)) + " repeated repeated"
    terms = skill_inventory.terms_of(description)
    assert len(terms) == 40 and len(set(terms)) == 40
