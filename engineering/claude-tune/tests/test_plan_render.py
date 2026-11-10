import json
import re
from pathlib import Path

import plan_render

TEMPLATE = Path(plan_render.TEMPLATE)
SETTINGS = "~/.claude/settings.json"


def mkitem(id, ops, risk="safe", deps=(), **over):
    base = {"id": id, "phase": int(id[1]), "title": f"title {id}", "risk": risk, "why": "because", "evidence": "e",
            "docs": "https://x", "impact": "i", "depends_on": list(deps), "consumers": [], "reversible": "full",
            "blast_radius": "user", "takes_effect": "next-session", "contains_secret": False,
            "checks": [{"phase": "deferred", "kind": "note", "text": "look"}], "status": "proposed", "ops": ops}
    base.update(over)
    return base


def mkplan(*items):
    return {"schema": 2, "generated": "2026-11-10T13:42:29", "window_days": 30, "claude_version": "v",
            "summary": "s", "items": list(items)}


def test_html_escapes_lt_in_json():
    item = mkitem("P1-01", [{"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}], title="<img src=x>")
    html = plan_render.render_html(mkplan(item), rendered_at="2026-11-10 14:00", plan_mtime="2026-11-10 13:42")
    body = html.split('id="plan"', 1)[1]
    assert "\\u003cimg" in body and "<img" not in body


def test_template_has_no_innerHTML():
    assert "innerHTML" not in TEMPLATE.read_text(encoding="utf-8")


def test_html_embeds_rendered_at_and_mtime():
    item = mkitem("P1-01", [{"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}])
    html = plan_render.render_html(mkplan(item), rendered_at="2026-11-10 14:00", plan_mtime="2026-11-10 13:42")
    assert 'data-rendered-at="2026-11-10 14:00"' in html and 'data-plan-mtime="2026-11-10 13:42"' in html


def test_html_escapes_attribute_values():
    item = mkitem("P1-01", [{"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}])
    html = plan_render.render_html(mkplan(item), rendered_at='x" onload="alert(1)', plan_mtime="m")
    assert 'onload="alert' not in html and "&quot;" in html


def test_md_lists_consumers_blockers_and_three_commands():
    manual = mkitem("P0-01", [{"kind": "manual", "text": "rotate"}], risk="manual")
    dep = mkitem("P0-03", [{"kind": "json_delete", "file": SETTINGS, "path": ["env", "X_TOKEN"]}], risk="review",
                 deps=["P0-01"], consumers=["~/.agents/skills/browserless/SKILL.md"])
    md = plan_render.render_md(mkplan(manual, dep))
    assert "Consumers: ~/.agents/skills/browserless/SKILL.md" in md
    assert "Blocked by: P0-01 (manual, not done)" in md
    assert "--dry-run" in md and "--expect" in md and "--done" in md
    assert "Checks: deferred note look" in md


def test_md_shows_effective_risk_when_floor_raises_it():
    item = mkitem("P1-02", [{"kind": "json_set", "file": SETTINGS, "path": ["statusLine", "command"], "value": "x"}])
    md = plan_render.render_md(mkplan(item))
    assert "`review`" in md and "declared safe" in md


def test_render_after_change_writes_md_and_html(tmp_path, monkeypatch):
    import render
    home = tmp_path / "home"
    plans = home / ".claude" / "tune" / "plans"
    plans.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    item = mkitem("P1-01", [{"kind": "json_set", "file": SETTINGS, "path": ["a"], "value": 1}])
    plan_path = plans / "p.json"
    plan_path.write_text(json.dumps(mkplan(item)))
    html_path = render.render_after_change(plan_path)
    assert html_path == plans / "p.json.html" and (plans / "p.json.md").exists()
    assert re.search(r'data-rendered-at="\d{4}-\d{2}-\d{2} \d{2}:\d{2}', html_path.read_text())


def test_html_embeds_effective_risk_per_item():
    item = mkitem("P1-02", [{"kind": "json_set", "file": SETTINGS, "path": ["statusLine", "command"], "value": "x"}])
    html = plan_render.render_html(mkplan(item), rendered_at="r", plan_mtime="m")
    assert '"risk_effective": "review"' in html
    tpl = TEMPLATE.read_text(encoding="utf-8")
    assert "risk_effective" in tpl and 'it.risk === "safe"' not in tpl
