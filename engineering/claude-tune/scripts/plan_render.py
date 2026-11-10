#!/usr/bin/env python3
"""Validate a claude-tune plan.json and render it as Markdown and as an HTML page.

Usage: plan_render.py PLAN.json [--md OUT.md] [--html OUT.html] [--latest]
--latest also points ~/.claude/tune/plans/latest.json at PLAN.json.
Exit 1 when the plan is invalid; the errors name the item and field.
Standard library only; never prints secret values (it prints no file contents).
"""
import argparse, json, os, re, sys

ID_RE = re.compile(r"^P\d-\d{2}$")
RISKS = ("safe", "review", "manual")
OP_KINDS = ("json_set", "json_delete", "json_append", "file_create", "file_append",
            "file_replace", "symlink", "file_remove", "manual")
REQUIRED = ("id", "phase", "title", "risk", "why", "evidence", "docs", "impact", "ops")
SECRET_RE = re.compile(r"sk_live_|rk_live_|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH) PRIVATE KEY")
PHASES = {0: "Security", 1: "Global config", 2: "Instruction files", 3: "Skills, rules, scripts",
          4: "Pipelines", 5: "Habits", 6: "Later"}
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "plan.html")


def validate(plan):
    errors = []
    if plan.get("schema") != 1:
        errors.append("schema must be 1")
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["items must be a non-empty list"]
    ids = [it.get("id") for it in items]
    for it in items:
        errors += validate_item(it, set(ids))
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate ids: {sorted(dupes)}")
    if SECRET_RE.search(json.dumps(plan)):
        errors.append("plan text matches a secret pattern; remove the value, keep the key name")
    return errors


def validate_item(it, all_ids):
    tag = f"item {it.get('id', '?')}"
    errs = [f"{tag}: missing {k}" for k in REQUIRED if k not in it]
    if not ID_RE.match(str(it.get("id", ""))):
        errs.append(f"{tag}: id must look like P1-02")
    if it.get("risk") not in RISKS:
        errs.append(f"{tag}: risk must be one of {RISKS}")
    if not isinstance(it.get("phase"), int) or it["phase"] not in PHASES:
        errs.append(f"{tag}: phase must be an integer 0-6")
    if it.get("docs") and not str(it["docs"]).startswith("https://"):
        errs.append(f"{tag}: docs must be a URL or empty with UNVERIFIED in impact")
    for dep in it.get("depends_on") or []:
        if dep not in all_ids:
            errs.append(f"{tag}: depends_on {dep} is not an item")
    ops = it.get("ops") or []
    if not ops:
        errs.append(f"{tag}: needs at least one op (use kind manual for user actions)")
    for n, op in enumerate(ops):
        errs += validate_op(op, f"{tag} op {n}")
    if it.get("risk") == "manual" and any(op.get("kind") != "manual" for op in ops):
        errs.append(f"{tag}: risk manual must carry only manual ops")
    return errs


def validate_op(op, tag):
    kind = op.get("kind")
    if kind not in OP_KINDS:
        return [f"{tag}: unknown kind {kind!r}"]
    need = {"json_set": ("file", "path", "value"), "json_delete": ("file", "path"), "json_append": ("file", "path", "values"),
            "file_create": ("file", "content"), "file_append": ("file", "content"), "file_replace": ("file", "old", "new"),
            "symlink": ("link", "target"), "file_remove": ("file",), "manual": ("text",)}[kind]
    errs = [f"{tag}: {kind} needs {k}" for k in need if k not in op]
    if kind.startswith("json_") and not isinstance(op.get("path"), list):
        errs.append(f"{tag}: path must be a list of keys")
    if op.get("file", "").endswith("/.claude.json") or op.get("file") == "~/.claude.json":
        errs.append(f"{tag}: ~/.claude.json may not be edited by a plan; use a manual op with the `claude mcp` command")
    return errs


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
    a = ap.parse_args()
    with open(a.plan, encoding="utf-8") as fh:
        plan = json.load(fh)
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
        latest = os.path.expanduser("~/.claude/tune/plans/latest.json")
        os.makedirs(os.path.dirname(latest), exist_ok=True)
        if os.path.lexists(latest): os.remove(latest)
        os.symlink(os.path.abspath(a.plan), latest)
    n = len(plan["items"]); by = {r: sum(1 for i in plan["items"] if i["risk"] == r) for r in RISKS}
    print(f"valid: {n} items (safe={by['safe']} review={by['review']} manual={by['manual']})"
          + (f"; md={a.md}" if a.md else "") + (f"; html={a.html}" if a.html else "") + ("; latest.json updated" if a.latest else ""))


if __name__ == "__main__":
    main()
