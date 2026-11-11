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


def test_page_header_is_one_stats_line_without_summary_or_legend():
    text = TEMPLATE.read_text(encoding="utf-8")
    header = text.split("<header>", 1)[1].split("</header>", 1)[0]
    assert 'id="summary"' not in text and 'id="legend"' not in text
    assert "Tick the changes you want" not in text and "days in window" not in text
    assert header.count("<p") <= 1 and 'id="stats"' in header


def test_main_prints_warnings_but_still_renders(tmp_path, monkeypatch, capsys):
    first = mkitem("P0-01", [{"kind": "manual", "text": "use the file from P0-02"}], risk="manual")
    second = mkitem("P0-02", [{"kind": "manual", "text": "make the file"}], risk="manual", deps=["P0-01"])
    plan_path = tmp_path / "p.json"
    plan_path.write_text(json.dumps(mkplan(first, second)))
    monkeypatch.setattr("sys.argv", ["plan_render.py", str(plan_path), "--md", str(tmp_path / "p.md")])
    plan_render.main()
    out = capsys.readouterr().out
    assert "WARNING: " in out and "P0-02" in out and out.rstrip().endswith("md=" + str(tmp_path / "p.md"))


STEPS = [{"text": "Create the secrets file", "code": "install -m 600 /dev/null ~/.config/claude/secrets.env"},
         {"text": "Restart the shell"}]


def test_md_renders_manual_steps_as_numbered_list_with_fenced_code():
    manual = mkitem("P0-02", [{"kind": "manual", "text": "one secrets file", "steps": STEPS}], risk="manual")
    md = plan_render.render_md(mkplan(manual))
    assert "- Op: manual: one secrets file" in md
    assert "  1. Create the secrets file" in md and "  2. Restart the shell" in md
    assert "```bash\n     install -m 600 /dev/null ~/.config/claude/secrets.env\n     ```" in md


def test_template_renders_steps_and_pins_the_highlighter_version():
    tpl = TEMPLATE.read_text()
    assert 'class="steps"' in tpl or '"steps"' in tpl
    assert re.search(r"cdnjs\.cloudflare\.com/ajax/libs/highlight\.js/\d+\.\d+\.\d+/highlight\.min\.js", tpl)
    assert "window.hljs" in tpl
    links = [line for line in tpl.splitlines() if line.startswith("<link")]
    assert all("fonts.googleapis.com" in line for line in links), "the artifact viewer blocks third-party stylesheets"
