#!/usr/bin/env python3
"""Validate a claude-tune plan.json and render it as Markdown and as an HTML page.

Usage: plan_render.py PLAN.json [--md OUT.md] [--html OUT.html] [--latest]
--latest also points ~/.claude/tune/plans/latest.json at PLAN.json (refused while the old plan
has applied items unless --force-latest).
Exit 1 when the plan is invalid; the errors name the item and field.
Validation lives in claude-tune-apply/scripts/plan_schema.py (shared). Prints no file contents.
"""
import argparse, json, os, sys

APPLY_SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "claude-tune-apply", "scripts")
sys.path.insert(0, os.path.realpath(APPLY_SCRIPTS))
from plan_schema import OP_KINDS, PHASES, RISKS, migrate_v1, validate  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "plan.html")


def render_md(plan):
    out = [f"# Claude Code tuning plan ({plan.get('window_days', '?')} days, generated {plan.get('generated', '')[:16]})", "",
           plan.get("summary", ""), ""]
    for ph in sorted({it["phase"] for it in plan["items"]}):
        out.append(f"## Phase {ph}: {PHASES.get(ph, '')}")
        for it in (i for i in plan["items"] if i["phase"] == ph):
            out.append(f"\n### {it['id']} {it['title']}  `{it['risk']}`" + (f"  status: {it['status']}" if it.get("status", "proposed") != "proposed" else ""))
            out.append(f"- Why: {it['why']}")
            out.append(f"- Evidence: {it['evidence']}")
            out.append(f"- Impact: {it['impact']}")
            out.append(f"- Docs: {it['docs'] or 'UNVERIFIED'}")
            if it.get("depends_on"):
                out.append(f"- Depends on: {', '.join(it['depends_on'])}")
            for op in it["ops"]:
                out.append(f"- Op: {op_line(op)}")
        out.append("")
    ids = [it["id"] for it in plan["items"] if it["risk"] == "safe"]
    out += ["## Apply", "", "Pick items and run, for example:", "", f"    /claude-tune-apply {' '.join(ids[:3])}", "",
            "`/claude-tune-apply safe` applies every safe item; `/claude-tune-apply --rollback P1-02` undoes one.", ""]
    return "\n".join(out)


def op_line(op):
    k = op["kind"]
    if k == "manual":
        return "manual: " + op["text"].replace("\n", " ")
    if k == "symlink":
        return f"symlink {op['link']} -> {op['target']}"
    path = "." .join(op["path"]) if isinstance(op.get("path"), list) else ""
    extra = f" = {json.dumps(op['value'])}" if "value" in op else (f" += {json.dumps(op['values'])}" if "values" in op else "")
    return f"{k} {op['file']} {path}{extra}".rstrip()


def render_html(plan):
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    safe_json = json.dumps(plan, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("{{PLAN_JSON}}", safe_json)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan"); ap.add_argument("--md"); ap.add_argument("--html"); ap.add_argument("--latest", action="store_true")
    ap.add_argument("--force-latest", action="store_true", help="repoint latest.json even if the old plan has applied items")
    a = ap.parse_args()
    with open(a.plan, encoding="utf-8") as fh:
        plan = migrate_v1(json.load(fh))
    errors = validate(plan)
    if errors:
        print("\n".join("INVALID: " + e for e in errors)); sys.exit(1)
    for it in plan["items"]:
        it.setdefault("status", "proposed"); it.setdefault("depends_on", [])
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh: fh.write(render_md(plan))
    if a.html:
        with open(a.html, "w", encoding="utf-8") as fh: fh.write(render_html(plan))
    if a.latest:
        from plan_store import point_latest
        from pathlib import Path
        point_latest(Path(a.plan), force=a.force_latest)
    n = len(plan["items"]); by = {r: sum(1 for i in plan["items"] if i["risk"] == r) for r in RISKS}
    print(f"valid: {n} items (safe={by['safe']} review={by['review']} manual={by['manual']})"
          + (f"; md={a.md}" if a.md else "") + (f"; html={a.html}" if a.html else "") + ("; latest.json updated" if a.latest else ""))


if __name__ == "__main__":
    main()
