"""Plan schema 2: constants, validation, effective risk, dependency order, v1 migration.

Owned by claude-tune-apply; claude-tune's renderer imports it from here so the two skills
never drift. Standard library only.
"""
import os
import re

from redact import has_secret

SCHEMA = 2
OP_KINDS = ("json_set", "json_delete", "json_append", "json_upsert", "file_create", "file_append",
            "file_replace", "symlink", "file_remove", "manual")
ID_RE = re.compile(r"P[0-6]-\d{2}")
RISKS = ("safe", "review", "manual")
STATUSES = ("proposed", "applied", "done", "needs_user", "rolled_back", "failed", "applied-purged")
REVERSIBLE = ("full", "setting-only", "none")
BLAST_RADIUS = ("user", "repo", "external")
TAKES_EFFECT = ("immediate", "next-session", "restart")
CHECK_PHASES = ("pre", "post", "deferred")
CHECK_KINDS = ("json_equals", "json_absent", "file_contains", "file_absent", "file_sha256",
               "file_mode", "cmd_exit", "note")
SENSITIVE_JSON_ROOTS = ("env", "permissions", "hooks", "statusLine", "mcpServers", "apiKeyHelper")
SENSITIVE_BASENAMES = ("CLAUDE.md", "AGENTS.md", "RULES.md")
REVIEW_OP_KINDS = ("json_delete", "file_remove", "file_replace", "symlink")
REQUIRED = ("id", "phase", "title", "risk", "why", "evidence", "docs", "impact", "ops")
PHASES = {0: "Security", 1: "Global config", 2: "Instruction files", 3: "Skills, rules, scripts",
          4: "Pipelines", 5: "Habits", 6: "Later"}
OP_FIELDS = {"json_set": ("file", "path", "value"), "json_delete": ("file", "path"),
             "json_append": ("file", "path", "values"), "json_upsert": ("file", "path", "match", "value"),
             "file_create": ("file", "content"), "file_append": ("file", "content"),
             "file_replace": ("file", "old", "new"), "symlink": ("link", "target"),
             "file_remove": ("file",), "manual": ("text",)}
ITEM_DEFAULTS = {"depends_on": [], "consumers": [], "reversible": "full", "blast_radius": "user",
                 "takes_effect": "next-session", "contains_secret": False, "checks": [], "status": "proposed"}


class PlanError(Exception):
    """A plan cannot be used as it stands; the message names the item and field."""


def validate(plan: dict) -> list[str]:
    """Every problem in the plan, as `item ID: ...` lines. Empty list means valid."""
    if plan.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA} (run the migration)"]
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        return ["items must be a non-empty list"]
    errors: list[str] = []
    for n, it in enumerate(items):
        if not isinstance(it, dict):
            errors.append(f"item #{n}: not an object")
    dict_items = [it for it in items if isinstance(it, dict)]
    ids = [str(it.get("id")) for it in dict_items]
    for it in dict_items:
        errors += _validate_item(it, set(ids))
    errors += _duplicate_ids(ids) + _validate_dependencies(dict_items)
    if has_secret(_text_of(plan)):
        errors.append("plan text matches a secret pattern; remove the value, keep the key name")
    return errors


def _text_of(plan: dict) -> str:
    import json
    return json.dumps(plan, ensure_ascii=False)


def _duplicate_ids(ids: list[str]) -> list[str]:
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    return [f"duplicate ids: {dupes}"] if dupes else []


def _validate_item(it: dict, all_ids: set[str]) -> list[str]:
    tag = f"item {it.get('id', '?')}"
    errs = [f"{tag}: missing {k}" for k in REQUIRED if k not in it]
    errs += _validate_item_enums(it, tag)
    if not ID_RE.fullmatch(str(it.get("id", ""))):
        errs.append(f"{tag}: id must look like P1-02")
    if not isinstance(it.get("phase"), int) or isinstance(it.get("phase"), bool) or it["phase"] not in PHASES:
        errs.append(f"{tag}: phase must be an integer 0-6")
    docs = str(it.get("docs", ""))
    if docs and not docs.startswith("https://"):
        errs.append(f"{tag}: docs must be an https URL")
    if not docs and "UNVERIFIED" not in str(it.get("impact", "")):
        errs.append(f"{tag}: docs empty requires UNVERIFIED in impact")
    errs += _validate_item_lists(it, tag, all_ids)
    errs += _validate_ops(it, tag)
    errs += [e for c in it.get("checks") or [] for e in _validate_check(c, tag)]
    return errs


def _validate_item_enums(it: dict, tag: str) -> list[str]:
    errs = []
    for field, allowed in (("risk", RISKS), ("reversible", REVERSIBLE), ("blast_radius", BLAST_RADIUS),
                           ("takes_effect", TAKES_EFFECT), ("status", STATUSES)):
        value = it.get(field, ITEM_DEFAULTS.get(field))
        if value not in allowed:
            errs.append(f"{tag}: {field} must be one of {allowed}")
    return errs


def _validate_item_lists(it: dict, tag: str, all_ids: set[str]) -> list[str]:
    errs = []
    deps = it.get("depends_on", [])
    if not isinstance(deps, list):
        errs.append(f"{tag}: depends_on must be a list of ids")
    else:
        errs += [f"{tag}: depends_on {d} is not an item" for d in deps if d not in all_ids]
    if not isinstance(it.get("consumers", []), list):
        errs.append(f"{tag}: consumers must be a list")
    elif not it.get("consumers") and _needs_consumers(it):
        errs.append(f"{tag}: consumers required when deleting a value or changing permissions or hooks")
    return errs


def _needs_consumers(it: dict) -> bool:
    for op in it.get("ops") or []:
        if not isinstance(op, dict):
            continue
        if op.get("kind") in ("json_delete", "file_remove"):
            return True
        if op.get("kind", "").startswith("json_") and _json_root(op) in ("permissions", "hooks"):
            return True  # whole-list replacements; a new env key has no consumer yet
    return False


def _validate_ops(it: dict, tag: str) -> list[str]:
    ops = it.get("ops") or []
    if not isinstance(ops, list) or not ops:
        return [f"{tag}: needs at least one op (use kind manual for user actions)"]
    errs = []
    for n, op in enumerate(ops):
        errs += _validate_op(op, f"{tag} op {n}")
    kinds = [op.get("kind") for op in ops if isinstance(op, dict)]
    if it.get("risk") == "manual" and any(k != "manual" for k in kinds):
        errs.append(f"{tag}: risk manual must carry only manual ops")
    if it.get("risk") != "manual" and "manual" in kinds:
        errs.append(f"{tag}: a manual op belongs only in a manual item")
    return errs


def _validate_op(op, tag: str) -> list[str]:
    if not isinstance(op, dict):
        return [f"{tag}: op is not an object"]
    kind = op.get("kind")
    if kind not in OP_KINDS:
        return [f"{tag}: unknown kind {kind!r}"]
    errs = [f"{tag}: {kind} needs {k}" for k in OP_FIELDS[kind] if k not in op]
    if kind.startswith("json_"):
        path = op.get("path")
        if not isinstance(path, list) or not path or not all(isinstance(k, str) for k in path):
            errs.append(f"{tag}: path must be a non-empty list of string keys")
    if kind == "json_append" and not isinstance(op.get("values"), list):
        errs.append(f"{tag}: values must be a list")
    if kind == "json_upsert" and not isinstance(op.get("match"), dict):
        errs.append(f"{tag}: match must be an object of key: value")
    target = str(op.get("file", ""))
    if target.endswith("/.claude.json") or target == "~/.claude.json":
        errs.append(f"{tag}: ~/.claude.json may not be edited by a plan; use a manual op with the `claude mcp` command")
    return errs


def _validate_check(check, tag: str) -> list[str]:
    if not isinstance(check, dict):
        return [f"{tag}: check is not an object"]
    errs = []
    if check.get("phase") not in CHECK_PHASES:
        errs.append(f"{tag}: check phase must be one of {CHECK_PHASES}")
    if check.get("kind") not in CHECK_KINDS:
        errs.append(f"{tag}: check kind must be one of {CHECK_KINDS}")
    if check.get("kind") == "cmd_exit" and not isinstance(check.get("argv"), list):
        errs.append(f"{tag}: cmd_exit needs argv as a list")
    return errs


def _validate_dependencies(items: list[dict]) -> list[str]:
    try:
        topo_order(items)
    except PlanError as exc:
        return [str(exc)]
    return []


def _json_root(op: dict) -> str:
    path = op.get("path")
    return str(path[0]) if isinstance(path, list) and path else ""


def _op_floor(op: dict) -> str:
    """The lowest risk an op may carry, from what it touches."""
    kind = op.get("kind")
    if kind == "manual":
        return "safe"
    if kind in REVIEW_OP_KINDS:
        return "review"
    if kind.startswith("json_") and _json_root(op) in SENSITIVE_JSON_ROOTS:
        return "review"
    target = os.path.expanduser(str(op.get("file") or op.get("link") or ""))
    if "/.claude/hooks/" in target or "/skills/" in target or os.path.basename(target) in SENSITIVE_BASENAMES:
        return "review"
    return "safe"


def effective_risk(item: dict) -> str:
    """Declared risk raised to the floor the ops and reversibility demand."""
    declared = item.get("risk", "review")
    if declared == "manual":
        return "manual"
    floors = [_op_floor(op) for op in item.get("ops") or [] if isinstance(op, dict)]
    if item.get("reversible", "full") != "full":
        floors.append("review")
    return "review" if declared == "review" or "review" in floors else "safe"


def item_touches_secret_root(item: dict) -> bool:
    return any(isinstance(op, dict) and op.get("kind", "").startswith("json_") and _json_root(op) == "env"
               for op in item.get("ops") or [])


def topo_order(items: list[dict]) -> list[dict]:
    """Items with every dependency before its dependents; ties broken by (phase, id)."""
    by_id = {it["id"]: it for it in items}
    pending = {it["id"]: [d for d in it.get("depends_on") or [] if d in by_id] for it in items}
    ordered: list[dict] = []
    while pending:
        ready = sorted((i for i, deps in pending.items() if not deps), key=lambda i: (by_id[i].get("phase", 9), i))
        if not ready:
            raise PlanError(f"dependency cycle among {sorted(pending)}")
        for i in ready:
            ordered.append(by_id[i])
            del pending[i]
        for deps in pending.values():
            deps[:] = [d for d in deps if d not in ready]
    return ordered


def migrate_v1(plan: dict) -> dict:
    """Upgrade a schema-1 plan in place: prose `verify` becomes a deferred note check."""
    if plan.get("schema") == 1:
        for it in plan.get("items") or []:
            if isinstance(it, dict):
                _migrate_item(it)
        plan["schema"] = SCHEMA
    return plan


def _migrate_item(it: dict) -> None:
    verify = it.pop("verify", "")
    for key, default in ITEM_DEFAULTS.items():
        it.setdefault(key, list(default) if isinstance(default, list) else default)
    if verify and not it["checks"]:
        it["checks"] = [{"phase": "deferred", "kind": "note", "text": verify}]
