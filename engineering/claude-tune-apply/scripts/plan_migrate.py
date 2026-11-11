"""Upgrade a schema-1 plan to schema 2 in place. Standard library only."""
from plan_schema import ITEM_DEFAULTS, SCHEMA


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
