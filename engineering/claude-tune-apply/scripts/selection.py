"""Which items a command names, which dependencies block them, and the manual-item ledger.

A dependency is satisfied when its status is applied or done, or when it already succeeded
earlier in this run, or when it is selected in this run and is not manual. A manual
dependency is never satisfied by selection: only `--done` records that the user did it.
"""
import datetime as dt
import re

from plan_risk import effective_risk
from plan_schema import PlanError, topo_order

GROUP_EXCLUDED = ("applied", "done", "rolled_back", "needs_user", "failed", "applied-purged")
SATISFIED_STATES = ("applied", "done")
PHASE_RE = re.compile(r"^(?:phase|p)(\d)$", re.I)


def by_id(plan: dict) -> dict:
    return {it["id"]: it for it in plan["items"]}


def _group(plan: dict, token: str) -> list[str] | None:
    """Ids a group token names, or None when the token is not a group."""
    items = [it for it in plan["items"] if it.get("status", "proposed") not in GROUP_EXCLUDED]
    if PHASE_RE.match(token):
        phase = int(PHASE_RE.match(token).group(1))
        return [it["id"] for it in items if it.get("phase") == phase]
    if token == "safe":
        return [it["id"] for it in items if effective_risk(it) == "safe"]
    if token == "all":
        return [it["id"] for it in items]
    return None


def select(plan: dict, tokens: list[str]) -> list[dict]:
    """Items for the tokens, dependency-ordered; explicit ids select anything, groups skip done work."""
    items = by_id(plan)
    chosen: set[str] = set()
    for tok in tokens:
        if tok in items:
            chosen.add(tok)
            continue
        group = _group(plan, tok)
        if group is None:
            raise PlanError(f"unknown selection token {tok!r}. Use ids like P1-02, phase1, safe or all.")
        chosen.update(group)
    if not chosen:
        raise PlanError("selection matched no item that is still open")
    return topo_order([items[i] for i in chosen])


def blockers(item: dict, plan: dict, succeeded: set[str], selected: set[str]) -> list[str]:
    """Dependency ids that are not yet satisfied for this item."""
    items = by_id(plan)
    out = []
    for dep in item.get("depends_on") or []:
        dep_item = items.get(dep, {})
        if dep_item.get("status") in SATISFIED_STATES or dep in succeeded:
            continue
        if dep in selected and dep_item.get("risk") != "manual":
            continue
        out.append(dep)
    return out


def _require(plan: dict, ids: list[str]) -> list[dict]:
    items = by_id(plan)
    missing = [i for i in ids if i not in items]
    if missing:
        raise PlanError(f"no item {', '.join(missing)}")
    return [items[i] for i in ids]


def mark_done(plan: dict, ids: list[str], run_post_checks=lambda item: None) -> list[str]:
    """Record manual items as done by the user; return the ids this unblocks."""
    chosen = _require(plan, ids)
    not_manual = [it["id"] for it in chosen if it.get("risk") != "manual"]
    if not_manual:
        raise PlanError(f"--done is for manual items only; {', '.join(not_manual)} must be applied")
    before = {it["id"] for it in plan["items"] if not blockers(it, plan, set(), set())}
    for it in chosen:
        run_post_checks(it)
        it["status"] = "done"
        it["done_at"] = dt.datetime.now().isoformat(timespec="seconds")
    after = {it["id"] for it in plan["items"] if not blockers(it, plan, set(), set())}
    return sorted(i for i in after - before if by_id(plan)[i].get("status", "proposed") == "proposed")


def mark_undone(plan: dict, ids: list[str]) -> None:
    for it in _require(plan, ids):
        if it.get("status") != "done":
            raise PlanError(f"{it['id']} is {it.get('status')}, not done")
        it["status"] = "proposed"
        it.pop("done_at", None)
