"""Operations a tuning plan item can carry, and how each one previews or applies.

Every op is idempotent: applying it twice yields the same files. Each `preview_*`
returns an OpResult describing the change without touching the disk; `write_result`
performs it. JSON ops live in ops_json.py, shared pieces in ops_base.py.
"""
import os

import ops_json
from ops_base import (ALLOWED_USER_ROOTS, OpResult, ReadError, SYSTEM_PREFIXES,  # noqa: F401 re-exported
                      check_path, expand, read_text, target_kind)
from plan_schema import OP_KINDS, PlanError


def preview_item_ops(ops):
    """Preview an item's ops in order; each op sees the text the previous one produced."""
    overlay, results = {}, []
    for op in ops:
        r = preview(op, overlay)
        results.append(r)
        if r.changed and not r.errors and r.kind not in ("manual", "symlink"):
            overlay[r.path] = r.after
    return results


def preview(op, overlay=None):
    kind = op.get("kind")
    if kind not in OP_KINDS:
        return OpResult(kind=str(kind), errors=[f"unknown op kind {kind!r}"])
    if kind == "manual":
        return OpResult(kind=kind, manual_text=op.get("text", ""), changed=False)
    target = op.get("link") if kind == "symlink" else op.get("file")
    if not target:
        return OpResult(kind=kind, errors=["op has no file/link"])
    try:
        real = check_path(target)
        return PREVIEWERS[kind](op, real, overlay)
    except (PlanError, ReadError) as exc:
        return OpResult(kind=kind, path=expand(target), errors=[str(exc)])


def preview_file_create(op, path, overlay=None):
    content = op.get("content", "")
    before = read_text(path, overlay)
    if before is not None and before != content:
        return OpResult(kind="file_create", path=path, before=before,
                        errors=["file exists with different content; use file_replace or file_append"])
    return OpResult(kind="file_create", path=path, before=before, after=content, changed=before is None)


def preview_file_append(op, path, overlay=None):
    content = op.get("content", "")
    before = read_text(path, overlay)
    if before is not None and content.strip() in before:
        return OpResult(kind="file_append", path=path, before=before, after=before, changed=False,
                        note="already present")
    base = before or ""
    sep = "" if (not base or base.endswith("\n")) else "\n"
    return OpResult(kind="file_append", path=path, before=before, after=base + sep + content, changed=True)


def preview_file_replace(op, path, overlay=None):
    old, new = op.get("old", ""), op.get("new", "")
    before = read_text(path, overlay)
    if before is None:
        return OpResult(kind="file_replace", path=path, errors=["file does not exist"])
    n = before.count(old)
    if n == 0 and new and new in before:
        return OpResult(kind="file_replace", path=path, before=before, after=before, changed=False, note="already replaced")
    if n != 1:
        return OpResult(kind="file_replace", path=path, before=before, errors=[f"old text occurs {n} times, need exactly 1"])
    return OpResult(kind="file_replace", path=path, before=before, after=before.replace(old, new, 1), changed=True)


def preview_symlink(op, path, overlay=None):
    target = op.get("target", "")
    if not target:
        return OpResult(kind="symlink", path=path, errors=["symlink needs target"])
    r = OpResult(kind="symlink", path=path, symlink_target=target)
    if os.path.islink(path):
        r.changed = os.readlink(path) != target
        if r.changed:
            r.errors.append(f"link exists and points to {os.readlink(path)}")
    elif os.path.exists(path):
        r.errors.append("path exists and is not a symlink")
    else:
        r.changed = True
    return r


def preview_file_remove(op, path, overlay=None):
    before = read_text(path, overlay)
    return OpResult(kind="file_remove", path=path, before=before, after=None, changed=before is not None)


PREVIEWERS = {
    **ops_json.PREVIEWERS,
    "file_create": preview_file_create, "file_append": preview_file_append,
    "file_replace": preview_file_replace, "symlink": preview_symlink, "file_remove": preview_file_remove,
}


def write_result(r):
    """Apply a previewed change. Caller has already backed the file up."""
    if not r.changed or r.errors or r.kind == "manual":
        return
    if r.kind == "symlink":
        os.makedirs(os.path.dirname(r.path), exist_ok=True)
        os.symlink(r.symlink_target, r.path)
        return
    if r.after is None:
        os.remove(r.path)
        return
    os.makedirs(os.path.dirname(r.path), exist_ok=True)
    with open(r.path, "w", encoding="utf-8") as fh:
        fh.write(r.after)
