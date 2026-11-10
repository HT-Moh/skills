"""Dry-run and apply: the same previews, bound together by a digest.

`dry_run` previews every selected item in dependency order over one shared overlay, so the
second item sees the first item's result, and returns a digest of what would be written.
`apply_items` recomputes that digest and refuses when it differs: the user approved a
specific set of diffs, and only that set gets written.
"""
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

import backup
import checks
import plan_store
import selection
import tune_ops
from plan_schema import PlanError, effective_risk, topo_order


@dataclass
class Preview:
    item_id: str
    results: list
    blockers: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _digest(previews: list) -> str:
    rows = [(p.item_id, r.kind, r.path, hashlib.sha256((r.after or "").encode("utf-8")).hexdigest())
            for p in previews for r in p.results]
    return hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()[:16]


def dry_run(plan: dict, items: list) -> tuple[list, str]:
    """Previews for the items (dependency order, shared overlay) and the digest of the writes."""
    ordered = topo_order(items)
    selected = {it["id"] for it in ordered}
    overlay: dict = {}
    previews = []
    for it in ordered:
        results = tune_ops.preview_item_ops(it.get("ops") or [], overlay)
        blockers = selection.blockers(it, plan, set(), selected)
        errors = [e for r in results for e in r.errors]
        previews.append(Preview(it["id"], results, blockers, errors))
    return previews, _digest(previews)


def _refuse_unconfirmed(items: list, confirmed: set) -> None:
    pending = [it["id"] for it in items if effective_risk(it) == "review" and it["id"] not in confirmed]
    if pending:
        raise PlanError(f"{', '.join(pending)} need review; re-run with --confirmed {','.join(pending)} "
                        f"after reading their diffs")


def _refuse_blocked(previews: list) -> None:
    blocked = [f"{p.item_id} needs {', '.join(p.blockers)}" for p in previews if p.blockers]
    if blocked:
        raise PlanError("; ".join(blocked) + ". Manual items count only after --done.")


def apply_items(plan: dict, items: list, plan_path, expect: str, confirmed: set) -> list:
    """Write the approved items in order; save the plan after each one; return summary lines."""
    previews, digest = dry_run(plan, items)
    if digest != expect:
        raise PlanError(f"state changed since the dry run (digest {digest}, expected {expect}); run --dry-run again")
    _refuse_unconfirmed(topo_order(items), confirmed)
    _refuse_blocked(previews)
    by_id = selection.by_id(plan)
    succeeded: set = set()
    lines = []
    for p in previews:
        item = by_id[p.item_id]
        lines += _apply_one(item, p, succeeded)
        plan_store.save_plan(plan, plan_path)
    return lines


def _apply_one(item: dict, preview: Preview, succeeded: set) -> list:
    if preview.errors:
        item.update(status="failed", error="; ".join(preview.errors))
        return [f"{item['id']}: failed: {item['error']}"]
    results = preview.results
    if all(r.kind == "manual" for r in results):
        item["status"] = "needs_user"
        return [f"{item['id']}: manual step; record it with --done {item['id']}"]
    pre = checks.failures(item, "pre")
    if pre:
        item.update(status="failed", error="; ".join(pre))
        return [f"{item['id']}: refused: {item['error']}"]
    if not any(r.changed for r in results):
        _finalize(item, results, None)
        succeeded.add(item["id"])
        return [f"{item['id']}: already in place, marked applied"]
    bdir = backup.make_backup(item["id"], results)
    error = _write_all(results) or _post_failure(item)
    if error:
        backup.restore_from(bdir)
        item.update(status="failed", error=error)
        return [f"{item['id']}: failed and restored: {error}"]
    backup.record_after_hashes(bdir)
    _finalize(item, results, bdir)
    succeeded.add(item["id"])
    return _lines_for(item, bdir) + [f"   note: {c.detail}" for c in checks.run_checks(item, "deferred")]


def _write_all(results: list) -> str:
    try:
        for r in results:
            tune_ops.write_result(r)
    except (OSError, PlanError) as exc:
        return str(exc)
    return ""


def _post_failure(item: dict) -> str:
    return "; ".join(checks.failures(item, "post"))


def _finalize(item: dict, results: list, bdir) -> None:
    has_manual = any(r.kind == "manual" for r in results)
    item.update(status="needs_user" if has_manual else "applied",
                applied_at=dt.datetime.now().isoformat(timespec="seconds"),
                files=sorted({r.path for r in results if r.changed and r.kind != "manual"}))
    item.pop("error", None)
    if bdir is not None:
        item["backup"] = str(bdir)


def _lines_for(item: dict, bdir) -> list:
    lines = [f"{item['id']}: {item['status']}; backup {bdir}; undo with /claude-tune-apply --rollback {item['id']}"]
    warning = secret_backup_warning(item, bdir)
    if warning:
        lines.append(warning)
    return lines


def secret_backup_warning(item: dict, bdir) -> str | None:
    manifest = backup.load_manifest(bdir)
    if not (manifest.get("contains_secret") or item.get("contains_secret")):
        return None
    return (f"WARNING backup {bdir} holds a credential value; once you have verified the change, "
            f"run /claude-tune-apply --purge-backup {item['id']} (rollback becomes impossible)")
