"""Repo-wide conventions for every skill folder (see CLAUDE.md)."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = sorted(p for p in ROOT.glob("*/*/SKILL.md") if p.parts[-3] not in (".claude", "tests"))
MAX_MODEL_INVOKED_DESCRIPTION = 600  # chars; the description sits in context on every turn
IDS = [str(p.parent.relative_to(ROOT)) for p in SKILLS]


def frontmatter(path):
    text = path.read_text(encoding="utf-8").split("---\n", 2)[1]
    out, key = {}, None
    for line in text.splitlines():
        if line.startswith("  ") and key:
            out[key] = (out[key] + " " + line.strip()).strip()
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        out[key] = "" if value.strip() in (">-", "") else value.strip()
    return out


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_name_matches_folder(skill):
    assert frontmatter(skill)["name"] == skill.parent.name


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_model_invoked_description_is_short(skill):
    fm = frontmatter(skill)
    if fm.get("disable-model-invocation") == "true":
        return
    assert len(fm["description"]) <= MAX_MODEL_INVOKED_DESCRIPTION, len(fm["description"])


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_readme_has_install_section(skill):
    readme = skill.parent / "README.md"
    assert readme.exists(), "every skill ships a README.md"
    assert re.search(r"^## Install", readme.read_text(encoding="utf-8"), re.M)


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_registered_in_manifest_and_readmes(skill):
    rel = skill.parent.relative_to(ROOT)
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    assert f"./{rel}" in manifest["skills"]
    assert skill.parent.name in (ROOT / "README.md").read_text()
    assert skill.parent.name in (ROOT / rel.parts[0] / "README.md").read_text()


def test_refactor_to_quality_fetches_examples_on_demand():
    skill = ROOT / "engineering" / "refactor-to-quality"
    assert (skill / "references" / "examples.md").exists()
    assert "WebFetch(domain:refactoring.guru)" in frontmatter(skill / "SKILL.md")["allowed-tools"]
    assert "references/examples.md" in (skill / "SKILL.md").read_text()


def test_marketplace_lists_the_root_plugin():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    assert market["name"] and market["owner"]["name"] and market["description"]
    entries = {e["name"]: e for e in market["plugins"]}
    assert entries[plugin["name"]]["source"] == "./"


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_evals_file_matches_skill_and_has_expectations(skill):
    evals = json.loads((skill.parent / "evals" / "evals.json").read_text(encoding="utf-8"))
    assert evals["skill_name"] == skill.parent.name
    assert len(evals["evals"]) >= 3
    for case in evals["evals"]:
        assert case["prompt"].strip() and len(case["expectations"]) >= 3, case["id"]


@pytest.mark.parametrize("skill", SKILLS, ids=IDS)
def test_model_invoked_skill_has_balanced_trigger_evals(skill):
    if frontmatter(skill).get("disable-model-invocation") == "true":
        return
    queries = json.loads((skill.parent / "evals" / "trigger_evals.json").read_text(encoding="utf-8"))
    positives = sum(1 for q in queries if q["should_trigger"])
    assert len(queries) == 20 and positives == 10, (len(queries), positives)
