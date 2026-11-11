#!/usr/bin/env python3
"""Apply, preview, explain or roll back selected items of a claude-tune plan.

  apply.py --list [--plan FILE]
  apply.py --dry-run SELECTION...          prints the diffs and a digest
  apply.py SELECTION... --expect DIGEST [--confirmed ID,ID]
  apply.py --explain ID
  apply.py --done ID... | --undone ID...   record manual items the user did
  apply.py --rollback ID... [--force]
  apply.py --purge-backup ID
  apply.py --render | --migrate

SELECTION: item ids (P1-02), phaseN or pN, `safe` (every open safe item), `all`.
A manual dependency counts only after --done. Review items are written only when named
in --confirmed. Every touched file is backed up under ~/.claude/tune/backups/ first.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup  # noqa: E402
import checks  # noqa: E402
import plan_store  # noqa: E402
import report  # noqa: E402
import runner  # noqa: E402
import selection  # noqa: E402
import tune_ops  # noqa: E402
from plan_risk import effective_risk  # noqa: E402
from plan_schema import PlanError, validate  # noqa: E402
from redact import redact  # noqa: E402


def say(text: str) -> None:
    print(redact(text))


def parse(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("selection", nargs="*")
    ap.add_argument("--plan")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--expect", metavar="DIGEST")
    ap.add_argument("--confirmed", metavar="IDS", default="")
    ap.add_argument("--rollback", nargs="+", metavar="ID")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--done", nargs="+", metavar="ID")
    ap.add_argument("--undone", nargs="+", metavar="ID")
    ap.add_argument("--explain", metavar="ID")
    ap.add_argument("--purge-backup", metavar="ID")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--migrate", action="store_true")
    ap.add_argument("--page", action="store_true")
    ap.add_argument("--set-page", metavar="URL")
    return ap.parse_args(argv)


def render_quietly(plan_path) -> None:
    """Re-render the Markdown and HTML beside the plan when the renderer is available."""
    try:
        import render
    except ImportError:
        return
    render.render_after_change(plan_path)


def cmd_dry_run(plan, items):
    previews, digest = runner.dry_run(plan, items)
    for p in previews:
        say(report.show_preview(p, selection.by_id(plan)[p.item_id], plan))
    blocked = sum(1 for p in previews if p.blockers)
    errors = sum(1 for p in previews if p.errors)
    would = sum(1 for p in previews if not p.blockers and not p.errors and any(r.changed for r in p.results))
    say(f"\nwould apply={would} blocked={blocked} errors={errors}\ndigest: {digest}\ndry run: nothing written.")
    ids = " ".join(p.item_id for p in previews)
    review = [p.item_id for p in previews if selection.by_id(plan)[p.item_id].get("risk") != "manual"
              and effective_risk(selection.by_id(plan)[p.item_id]) == "review"]
    confirmed = f" --confirmed {','.join(review)}" if review else ""
    say(f"apply: /claude-tune-apply {ids} --expect {digest}{confirmed}")


def cmd_apply(plan, items, plan_path, a):
    if not a.expect:
        raise PlanError("run --dry-run first, read the diffs, then pass its digest with --expect <digest>")
    confirmed = {c for c in a.confirmed.split(",") if c}
    for line in runner.apply_items(plan, items, plan_path, expect=a.expect, confirmed=confirmed):
        say(line)
    say("settings, hooks and CLAUDE.md changes load in the next session.")


def cmd_rollback(plan, plan_path, ids, force):
    by_id = selection.by_id(plan)
    for item_id in ids:
        item = by_id.get(item_id)
        if item is None:
            raise PlanError(f"no item {item_id}")
        for warning in backup.rollback_item(plan, item, force=force):
            say(warning)
        plan_store.save_plan(plan, plan_path)
        say(f"{item_id} rolled back")


def cmd_done(plan, plan_path, ids):
    unblocked = selection.mark_done(plan, ids, run_post_checks=checks.require_post)
    plan_store.save_plan(plan, plan_path)
    say(f"{', '.join(ids)} marked done" + (f"; now unblocked: {', '.join(unblocked)}" if unblocked else ""))


def cmd_undone(plan, plan_path, ids):
    selection.mark_undone(plan, ids)
    plan_store.save_plan(plan, plan_path)
    say(f"{', '.join(ids)} back to proposed")


def cmd_purge(plan, plan_path, item_id):
    item = selection.by_id(plan).get(item_id)
    if item is None or item.get("status") != "applied":
        raise PlanError(f"{item_id} is not an applied item with a backup")
    backup.purge_backup(backup.backup_dir_for(item))
    item["status"] = "applied-purged"
    plan_store.save_plan(plan, plan_path)
    say(f"{item_id}: backup purged; rollback is no longer possible")


def cmd_set_page(plan, plan_path, url):
    plan["page_url"] = url
    errors = validate(plan)
    if errors:
        raise PlanError("\n".join(errors))
    plan_store.save_plan(plan, plan_path)
    say(f"page recorded: {url}")


def cmd_migrate(plan, plan_path):
    raised = [it["id"] for it in plan["items"] if it.get("risk") == "safe" and effective_risk(it) == "review"]
    plan_store.save_plan(plan, plan_path)
    say(f"{plan_path}: schema {plan['schema']} saved" + (f"; effective risk is review for: {', '.join(raised)}" if raised else ""))


def dispatch(a) -> None:
    plan, plan_path = plan_store.load_plan(a.plan)
    if a.explain:
        item = selection.by_id(plan).get(a.explain)
        if item is None:
            raise PlanError(f"no item {a.explain}")
        return say(report.explain(item, plan))
    if a.page:
        return say(report.page_lines(plan, plan_path))
    if a.set_page:
        cmd_set_page(plan, plan_path, a.set_page)
    elif a.rollback:
        cmd_rollback(plan, plan_path, a.rollback, a.force)
    elif a.done:
        cmd_done(plan, plan_path, a.done)
    elif a.undone:
        cmd_undone(plan, plan_path, a.undone)
    elif a.purge_backup:
        cmd_purge(plan, plan_path, a.purge_backup)
    elif a.migrate:
        cmd_migrate(plan, plan_path)
    elif a.selection and a.dry_run:
        return cmd_dry_run(plan, selection.select(plan, a.selection))
    elif a.selection:
        cmd_apply(plan, selection.select(plan, a.selection), plan_path, a)
    elif not a.render:
        return say(report.list_table(plan))
    render_quietly(plan_path)


def main(argv) -> int:
    a = parse(argv)
    tune_ops.secure_umask()
    if a.list and not os.path.exists(a.plan or plan_store.latest_path()):
        say(f"no plan at {a.plan or plan_store.latest_path()}. Run /claude-tune first.")
        return 0
    try:
        with plan_store.locked():
            dispatch(a)
    except PlanError as exc:
        say(f"ERROR {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
