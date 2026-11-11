"""Plan smells that do not invalidate a plan but mislead the user. Standard library only."""
from plan_schema import ID_RE


def warnings(plan: dict) -> list[str]:
    """Order smells that do not invalidate the plan: an item's text leans on an item that waits for it."""
    items = [it for it in plan.get("items") or [] if isinstance(it, dict)]
    by_id = {it.get("id"): it for it in items}
    out = []
    for it in items:
        text = " ".join(str(op.get("text", "")) for op in it.get("ops") or [] if isinstance(op, dict))
        for ref in sorted(set(ID_RE.findall(text))):
            if it.get("id") in (by_id.get(ref) or {}).get("depends_on", []):
                out.append(f"item {it['id']}: its text uses {ref}, but {ref} depends on {it['id']}; "
                           f"swap the dependency or rewrite the text")
    return out
