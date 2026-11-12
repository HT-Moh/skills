"""Everything the apply skill prints: item explanations, previews with warnings, the table.

Every string leaves through `redact`, so a credential never reaches the terminal or the
model, whatever the plan or the files contain.
"""
import json
from pathlib import Path

import consumers
import selection
from plan_risk import effective_risk
from plan_schema import SENSITIVE_JSON_ROOTS
from redact import redact

EXEC_ROOTS = ("hooks", "statusLine", "apiKeyHelper")


def _floor_reason(item: dict) -> str:
    """Why the effective risk is review when the plan declared safe."""
    reasons = []
    for op in item.get("ops") or []:
        path = op.get("path") or []
        if path and str(path[0]) in SENSITIVE_JSON_ROOTS:
            reasons.append(f"writes under {path[0]}")
        if op.get("kind") in ("json_delete", "file_remove", "file_replace", "symlink"):
            reasons.append(f"op kind {op['kind']}")
    if item.get("reversible", "full") != "full":
        reasons.append(f"reversible={item['reversible']}")
    return ", ".join(sorted(set(reasons)))


def _dependency_lines(item: dict, plan: dict) -> list[str]:
    by_id = selection.by_id(plan)
    out = []
    for dep in item.get("depends_on") or []:
        dep_item = by_id.get(dep, {})
        out.append(f"  - {dep} [{dep_item.get('risk', '?')}] {dep_item.get('status', 'proposed')}: {dep_item.get('title', '')}")
    return out or ["  - none"]


def _check_lines(item: dict) -> list[str]:
    out = []
    for c in item.get("checks") or []:
        detail = c.get("text") or c.get("file") or " ".join(c.get("argv") or [])
        out.append(f"  - {c.get('phase')}: {c.get('kind')} {detail}")
    return out or ["  - none"]


def _step_lines(item: dict) -> list[str]:
    out = []
    for op in item.get("ops") or []:
        if op.get("kind") != "manual":
            continue
        steps = op.get("steps") or []
        if not steps:
            out.append(f"  - {op.get('text', '')}")
        for n, step in enumerate(steps, 1):
            out.append(f"  {n}. {step['text']}")
            out += ["     " + line for line in (step.get("code") or "").splitlines()]
    return out


def explain(item: dict, plan: dict) -> str:
    """Why, evidence, impact, risk with its floor reason, consumers, dependencies, checks."""
    declared, effective = item.get("risk"), effective_risk(item)
    risk = effective if declared == effective else f"{effective} (declared {declared}; floor: {_floor_reason(item)})"
    discovered = consumers.find_consumers(consumers.key_names_touched(item)) if consumers.key_names_touched(item) else []
    lines = [f"{item['id']}  {item.get('title', '')}", f"risk: {risk}", f"why: {item.get('why', '')}",
             f"evidence: {item.get('evidence', '')}", f"impact: {item.get('impact', '')}",
             f"reversible: {item.get('reversible', 'full')}; takes effect: {item.get('takes_effect', 'next-session')}; "
             f"blast radius: {item.get('blast_radius', 'user')}",
             "consumers (declared): " + (", ".join(item.get("consumers") or []) or "none declared"),
             "consumers (found by grep): " + (", ".join(discovered) or "none found"),
             "depends on:", *_dependency_lines(item, plan), "checks:", *_check_lines(item),
             *(["steps:", *_step_lines(item)] if item.get("risk") == "manual" else []),
             f"docs: {item.get('docs') or 'UNVERIFIED'}"]
    return redact("\n".join(lines))


def _warnings(preview, item: dict) -> list[str]:
    out = []
    for r in preview.results:
        if r.kind == "manual" or not r.changed:
            continue
        if "/.claude/hooks/" in r.path:
            out.append(f"WARNING EXEC {r.path} is a hook script; it runs on every matching tool call")
    for op in item.get("ops") or []:
        path = op.get("path") or []
        root = str(path[0]) if path else ""
        if root in EXEC_ROOTS:
            out.append(f"WARNING EXEC writes {'.'.join(map(str, path))}: this configures code Claude Code runs")
        if root == "permissions":
            out.append(_permission_warning(op, preview))
    return [w for w in out if w]


def _permission_warning(op: dict, preview) -> str:
    path = ".".join(map(str, op.get("path") or []))
    removed = _removed_list_entries(op, preview)
    tail = f"; removes {', '.join(removed)}" if removed else ""
    return f"WARNING PERMISSION writes {path}: this widens or narrows what runs without asking{tail}"


def _removed_list_entries(op: dict, preview) -> list[str]:
    if op.get("kind") != "json_set" or not isinstance(op.get("value"), list):
        return []
    for r in preview.results:
        if r.path == _real(op) and r.before:
            try:
                node = json.loads(r.before)
                for k in op["path"]:
                    node = node[k]
            except (ValueError, KeyError, TypeError):
                return []
            return [str(v) for v in node if v not in op["value"]] if isinstance(node, list) else []
    return []


def _real(op: dict) -> str:
    import os
    return os.path.abspath(os.path.expanduser(op.get("file", "")))


def show_preview(preview, item: dict, plan: dict) -> str:
    """One item's dry-run block: header, warnings, consumers, blockers, then each op's diff."""
    lines = [f"== {item['id']}  {item.get('title', '')}  [{effective_risk(item)}]"]
    lines += [f"   {w}" for w in _warnings(preview, item)]
    if item.get("consumers"):
        lines.append("   consumers: " + ", ".join(item["consumers"]))
    if preview.blockers:
        lines.append(f"   blocked by {', '.join(preview.blockers)} (manual items count only after --done)")
    if item.get("checks"):
        lines.append("   checks:")
        lines += ["   " + line for line in _check_lines(item)]
    for r in preview.results:
        lines += _result_lines(r)
    return redact("\n".join(lines))


def _result_lines(r) -> list[str]:
    if r.kind == "manual":
        return ["   MANUAL: " + r.manual_text.replace("\n", "\n           ")]
    if r.errors:
        return [f"   ERROR {r.kind} {r.path}: {'; '.join(r.errors)}"]
    if not r.changed:
        return [f"   skip  {r.kind} {r.path} ({r.note or 'no change needed'})"]
    head = [f"   {r.kind} {r.path}"]
    diff = r.diff()
    return head + (["   " + diff.rstrip().replace("\n", "\n   ")] if diff else [])


def _blocked_by(item: dict, plan: dict) -> str:
    return ",".join(selection.blockers(item, plan, set(), set()))


def _next_line(plan: dict) -> str:
    for it in plan["items"]:
        if it.get("status", "proposed") != "proposed" or _blocked_by(it, plan):
            continue
        if it.get("risk") == "manual":
            return f"Next: {it['id']} is a manual step; do it, then /claude-tune-apply --done {it['id']}"
        return f"Next: /claude-tune-apply --dry-run {it['id']}"
    return "Next: nothing open; every item is applied, done or blocked"


def page_lines(plan: dict, plan_path) -> str:
    """Where the plan's Artifact page lives, and the HTML to republish there after a change."""
    html_path = Path(plan_path).with_name(Path(plan_path).name + ".html")
    url = plan.get("page_url")
    if not url:
        return f"no page recorded. Publish {html_path} with the Artifact tool, then: apply.py --set-page <url>\nhtml: {html_path}"
    return f"page: {url}\nhtml: {html_path}"


def list_table(plan: dict) -> str:
    lines = [f"plan: {plan.get('generated', '?')}  window={plan.get('window_days', '?')}d  items={len(plan['items'])}",
             "id     ph risk    status      blocked-by   title"]
    for it in plan["items"]:
        lines.append(f"{it['id']:<6} {it.get('phase', '?'):<2} {effective_risk(it):<7} {it.get('status', 'proposed'):<11} "
                     f"{_blocked_by(it, plan):<12} {it.get('title', '')[:60]}")
    lines += ["", _next_line(plan),
              "apply:  /claude-tune-apply --dry-run P1-01 P1-03   then   /claude-tune-apply P1-01 P1-03 --expect <digest>",
              "manual: /claude-tune-apply --done P0-01      undo: /claude-tune-apply --rollback P1-03"]
    if plan.get("page_url"):
        lines.append(f"page: {plan['page_url']}")
    return redact("\n".join(lines))
