#!/usr/bin/env python3
"""Apply, preview or roll back selected items of a claude-tune plan.

Usage:
  apply.py --list [--plan FILE]
  apply.py [--dry-run] SELECTION... [--plan FILE]
  apply.py --rollback ID [--plan FILE]
  apply.py --done ID [--plan FILE]          # mark a manual item as done by the user

SELECTION: item ids (P1-02), phaseN or pN, `safe` (every unapplied safe item),
`all` (every unapplied item; manual ones are printed, not executed).
Every touched file is copied to ~/.claude/tune/backups/<timestamp>_<id>/ first.
"""
import argparse, datetime as dt, json, os, re, shutil, stat, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tune_ops  # noqa: E402

TUNE_DIR = os.path.expanduser("~/.claude/tune")
DEFAULT_PLAN = os.path.join(TUNE_DIR, "plans", "latest.json")
BACKUP_ROOT = os.path.join(TUNE_DIR, "backups")
ID_RE = re.compile(r"^P\d-\d{2}$")
PHASE_RE = re.compile(r"^(?:phase|p)(\d)$", re.I)
APPLIED_STATES = ("applied", "done")


def load_plan(path):
    with open(path, encoding="utf-8") as fh:
        plan = json.load(fh)
    if plan.get("schema") != 1 or not isinstance(plan.get("items"), list):
        sys.exit(f"{path}: not a schema-1 claude-tune plan")
    return plan


def save_plan(path, plan):
    real = os.path.realpath(path)
    tmp = real + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, real)


def by_id(plan):
    return {it["id"]: it for it in plan["items"]}


def select(plan, tokens):
    items = by_id(plan)
    chosen, unknown = [], []
    for tok in tokens:
        if tok in items:
            chosen.append(tok)
        elif PHASE_RE.match(tok):
            ph = int(PHASE_RE.match(tok).group(1))
            chosen += [i["id"] for i in plan["items"] if i.get("phase") == ph and i.get("status") not in APPLIED_STATES]
        elif tok == "safe":
            chosen += [i["id"] for i in plan["items"] if i.get("risk") == "safe" and i.get("status") not in APPLIED_STATES]
        elif tok == "all":
            chosen += [i["id"] for i in plan["items"] if i.get("status") not in APPLIED_STATES]
        else:
            unknown.append(tok)
    if unknown:
        sys.exit(f"unknown selection token(s): {' '.join(unknown)}. Use ids like P1-02, phase1, safe or all.")
    ordered = sorted(set(chosen), key=lambda i: (items[i].get("phase", 9), i))
    return [items[i] for i in ordered]


def missing_dependencies(item, selected_ids, items):
    out = []
    for dep in item.get("depends_on") or []:
        if dep in selected_ids:
            continue
        if items.get(dep, {}).get("status") not in APPLIED_STATES:
            out.append(dep)
    return out


def print_list(plan):
    print(f"plan: {plan.get('generated', '?')}  window={plan.get('window_days', '?')}d  items={len(plan['items'])}")
    print("id     ph risk    status      title")
    for it in plan["items"]:
        print(f"{it['id']:<6} {it.get('phase', '?'):<2} {it.get('risk', '?'):<7} {it.get('status', 'proposed'):<11} {it.get('title', '')[:70]}")
    print("\napply:  /claude-tune-apply P0-01 P1-03    or  phase1  or  safe\nrollback: /claude-tune-apply --rollback P1-03")


def preview_item(item):
    results = tune_ops.preview_item_ops(item.get("ops") or [])
    errors = [e for r in results for e in r.errors]
    return results, errors


def make_backup(item, results):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(BACKUP_ROOT, f"{stamp}_{item['id']}")
    os.makedirs(bdir, mode=0o700, exist_ok=True)
    manifest = {"item": item["id"], "created": stamp, "files": []}
    seen = set()
    for n, r in enumerate(results):
        if not r.changed or r.kind == "manual" or r.path in seen:
            continue
        seen.add(r.path)
        entry = {"path": r.path, "kind": r.kind, "existed": os.path.lexists(r.path), "saved_as": "",
                 "parent_existed": os.path.isdir(os.path.dirname(r.path))}
        if entry["existed"] and not os.path.islink(r.path) and os.path.isfile(r.path):
            entry["saved_as"] = f"{n:02d}_{os.path.basename(r.path)}"
            shutil.copy2(r.path, os.path.join(bdir, entry["saved_as"]))
            os.chmod(os.path.join(bdir, entry["saved_as"]), stat.S_IRUSR | stat.S_IWUSR)
        manifest["files"].append(entry)
    with open(os.path.join(bdir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    return bdir


def show_item(item, results, errors):
    print(f"\n== {item['id']}  {item.get('title', '')}  [{item.get('risk', '?')}]")
    for r in results:
        if r.kind == "manual":
            print("   MANUAL: " + r.manual_text.replace("\n", "\n           "))
        elif r.errors:
            print(f"   ERROR {r.kind} {r.path}: {'; '.join(r.errors)}")
        elif not r.changed:
            print(f"   skip  {r.kind} {r.path} ({r.note or 'no change needed'})")
        else:
            print(f"   {r.kind} {r.path}")
            d = r.diff()
            if d and r.kind != "symlink":
                print("   " + d.rstrip().replace("\n", "\n   "))
    return not errors


def run(plan, plan_path, items, dry):
    all_items = by_id(plan)
    selected_ids = {i["id"] for i in items}
    counts = {"applied": 0, "failed": 0, "unchanged": 0, "manual": 0}
    for item in items:
        deps = missing_dependencies(item, selected_ids, all_items)
        results, errors = preview_item(item)
        if deps:
            errors.append(f"depends on {', '.join(deps)} which is not applied and not selected")
        ok = show_item(item, results, errors)
        if deps:
            print(f"   ERROR {errors[-1]}")
        if not ok:
            counts["failed"] += 1
            continue
        if all(r.kind == "manual" for r in results):
            counts["manual"] += 1
            if not dry:
                item["status"] = "needs_user"
            continue
        if not any(r.changed for r in results):
            counts["unchanged"] += 1
            if not dry:
                item["status"] = "applied"; item["applied_at"] = dt.datetime.now().isoformat()
            continue
        if dry:
            counts["applied"] += 1
            continue
        bdir = make_backup(item, results)
        for r in results:
            tune_ops.write_result(r)
        item.update(status="applied", applied_at=dt.datetime.now().isoformat(), backup=bdir,
                    files=sorted({r.path for r in results if r.changed and r.kind != "manual"}))
        counts["applied"] += 1
        print(f"   applied; backup {bdir}")
    if not dry:
        save_plan(plan_path, plan)
    label = "would apply" if dry else "applied"
    print(f"\n{label}={counts['applied']} unchanged={counts['unchanged']} manual={counts['manual']} failed={counts['failed']}")
    if dry:
        print("dry run: nothing written.")
    elif counts["applied"]:
        print("rollback one item: /claude-tune-apply --rollback <id>")
    return counts["failed"] == 0


def rollback(plan, plan_path, item_id):
    item = by_id(plan).get(item_id) or sys.exit(f"no item {item_id}")
    bdir = item.get("backup") or sys.exit(f"{item_id} has no backup recorded (status {item.get('status')})")
    with open(os.path.join(bdir, "manifest.json")) as fh:
        manifest = json.load(fh)
    for f in manifest["files"]:
        if f["existed"] and f["saved_as"]:
            shutil.copy2(os.path.join(bdir, f["saved_as"]), f["path"])
            print(f"restored {f['path']}")
        elif not f["existed"] and os.path.lexists(f["path"]):
            os.remove(f["path"])
            if not f.get("parent_existed", True):
                remove_empty_parent(f["path"])
            print(f"removed  {f['path']} (did not exist before)")
    item["status"] = "rolled_back"
    for later in later_items_sharing_files(plan, item):
        later["status"] = "proposed"
        print(f"WARNING {later['id']} was applied after {item_id} on the same file; its change is gone too. "
              f"Re-apply with: /claude-tune-apply {later['id']}")
    save_plan(plan_path, plan)
    print(f"{item_id} rolled back from {bdir}")


def later_items_sharing_files(plan, item):
    files = set(item.get("files") or [])
    return [o for o in plan["items"] if o is not item and o.get("status") == "applied"
            and (o.get("applied_at") or "") > (item.get("applied_at") or "") and files & set(o.get("files") or [])]


def remove_empty_parent(path):
    parent = os.path.dirname(path)
    try:
        os.rmdir(parent)  # only succeeds when empty
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("selection", nargs="*")
    ap.add_argument("--plan", default=DEFAULT_PLAN)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", metavar="ID")
    ap.add_argument("--done", metavar="ID")
    a = ap.parse_args()
    if not os.path.exists(a.plan):
        print(f"no plan at {a.plan}. Run /claude-tune first.")
        sys.exit(0 if (a.list or not a.selection) else 1)
    plan = load_plan(a.plan)
    if a.rollback:
        return rollback(plan, a.plan, a.rollback)
    if a.done:
        item = by_id(plan).get(a.done) or sys.exit(f"no item {a.done}")
        item["status"] = "done"; save_plan(a.plan, plan); return print(f"{a.done} marked done")
    if a.list or not a.selection:
        return print_list(plan)
    ok = run(plan, a.plan, select(plan, a.selection), a.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
