#!/usr/bin/env python3
"""Validate a claude-tune plan.json and render it as Markdown and as an HTML page.

Usage: plan_render.py PLAN.json [--md OUT.md] [--html OUT.html] [--latest] [--force-latest]
--latest also points ~/.claude/tune/plans/latest.json at PLAN.json (refused while the old plan
has applied items unless --force-latest).
Exit 1 when the plan is invalid; the errors name the item and field.
Validation lives in claude-tune-apply/scripts/plan_schema.py (shared). Prints no file contents.
"""
import argparse
import datetime as dt
import html
import json
import os
import sys

APPLY_SCRIPTS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..", "claude-tune-apply", "scripts")
sys.path.insert(0, os.path.realpath(APPLY_SCRIPTS))
from plan_schema import PHASES, RISKS, effective_risk, migrate_v1, validate  # noqa: E402
from redact import redact  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "plan.html")
TIME_FMT = "%Y-%m-%d %H:%M"


def blockers_of(item, plan):
    """Dependencies not yet satisfied, each with the reason it blocks."""
    by_id = {it["id"]: it for it in plan["items"]}
    out = []
    for dep in item.get("depends_on") or []:
        d = by_id.get(dep, {})
        status = d.get("status", "proposed")
        if status in ("applied", "done"):
            continue
        out.append(f"{dep} (manual, not done)" if d.get("risk") == "manual" else f"{dep} ({status})")
    return out


def _risk_label(item):
    declared, effective = item.get("risk"), effective_risk(item)
    return f"`{effective}`" + (f" (declared {declared})" if declared != effective else "")


def _item_md(item, plan):
    status = item.get("status", "proposed")
    out = [f"\n### {item['id']} {item['title']}  {_risk_label(item)}" + (f"  status: {status}" if status != "proposed" else ""),
           f"- Why: {item['why']}", f"- Evidence: {item['evidence']}", f"- Impact: {item['impact']}",
           f"- Reversible: {item.get('reversible', 'full')}; takes effect: {item.get('takes_effect', 'next-session')}",
           f"- Docs: {item['docs'] or 'UNVERIFIED'}"]
    if item.get("consumers"):
        out.append(f"- Consumers: {', '.join(item['consumers'])}")
    blockers = blockers_of(item, plan)
    if blockers:
        out.append(f"- Blocked by: {', '.join(blockers)}")
    elif item.get("depends_on"):
        out.append(f"- Depends on: {', '.join(item['depends_on'])}")
    for c in item.get("checks") or []:
        out.append(f"- Checks: {c.get('phase')} {c.get('kind')} {c.get('text') or c.get('file') or ' '.join(c.get('argv') or [])}")
    out += [f"- Op: {op_line(op)}" for op in item["ops"]]
    return out


def render_md(plan):
    out = [f"# Claude Code tuning plan ({plan.get('window_days', '?')} days, generated {plan.get('generated', '')[:16]})", "",
           plan.get("summary", ""), "",
           "Risk: `safe` = reversible, no judgement needed; `review` = read the diff (deletes, env, permissions, "
           "hooks, instruction files); `manual` = only you can do it, then record it with `--done`.", ""]
    for ph in sorted({it["phase"] for it in plan["items"]}):
        out.append(f"## Phase {ph}: {PHASES.get(ph, '')}")
        for it in (i for i in plan["items"] if i["phase"] == ph):
            out += _item_md(it, plan)
        out.append("")
    safe = [it["id"] for it in plan["items"] if effective_risk(it) == "safe"][:3]
    manual = [it["id"] for it in plan["items"] if it["risk"] == "manual"][:2]
    out += ["## Apply", "", "1. Preview: `/claude-tune-apply --dry-run " + " ".join(safe) + "`",
            "2. Apply what you read: `/claude-tune-apply " + " ".join(safe) + " --expect <digest from the dry run>`",
            "3. Manual items, once done: `/claude-tune-apply --done " + " ".join(manual) + "`",
            "", "`/claude-tune-apply --rollback P1-02` undoes one item; `--explain P1-02` shows why, consumers and checks.", ""]
    return redact("\n".join(out))


def op_line(op):
    k = op["kind"]
    if k == "manual":
        return "manual: " + op["text"].replace("\n", " ")
    if k == "symlink":
        return f"symlink {op['link']} -> {op['target']}"
    path = ".".join(op["path"]) if isinstance(op.get("path"), list) else ""
    extra = f" = {json.dumps(op['value'])}" if "value" in op else (f" += {json.dumps(op['values'])}" if "values" in op else "")
    return f"{k} {op['file']} {path}{extra}".rstrip()


def render_html(plan, rendered_at, plan_mtime):
    with open(TEMPLATE, encoding="utf-8") as fh:
        tpl = fh.read()
    safe_json = json.dumps(plan, ensure_ascii=False).replace("<", "\\u003c")
    return (tpl.replace("{{PLAN_JSON}}", safe_json)
            .replace("{{RENDERED_AT}}", html.escape(rendered_at, quote=True))
            .replace("{{PLAN_MTIME}}", html.escape(plan_mtime, quote=True)))


def render_files(plan, plan_path, md_path, html_path):
    """Write both renders beside the plan with owner-only modes."""
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(plan_path)).strftime(TIME_FMT)
    now = dt.datetime.now().strftime(TIME_FMT)
    for path, text in ((md_path, render_md(plan)), (html_path, render_html(plan, now, mtime))):
        if path:
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
                fh.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--md")
    ap.add_argument("--html")
    ap.add_argument("--latest", action="store_true")
    ap.add_argument("--force-latest", action="store_true", help="repoint latest.json even if the old plan has applied items")
    a = ap.parse_args()
    with open(a.plan, encoding="utf-8") as fh:
        plan = migrate_v1(json.load(fh))
    errors = validate(plan)
    if errors:
        print("\n".join("INVALID: " + e for e in errors))
        sys.exit(1)
    render_files(plan, a.plan, a.md, a.html)
    if a.latest:
        from pathlib import Path
        from plan_store import point_latest
        point_latest(Path(a.plan), force=a.force_latest)
    n = len(plan["items"])
    by = {r: sum(1 for i in plan["items"] if effective_risk(i) == r) for r in RISKS}
    print(f"valid: {n} items (safe={by['safe']} review={by['review']} manual={by['manual']})"
          + (f"; md={a.md}" if a.md else "") + (f"; html={a.html}" if a.html else "") + ("; latest.json updated" if a.latest else ""))


if __name__ == "__main__":
    main()
