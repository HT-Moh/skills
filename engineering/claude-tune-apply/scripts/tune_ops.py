"""Operations a tuning plan item can carry, and how each one previews or applies.

Every op is idempotent: applying it twice yields the same files. Each `preview_*`
returns an OpResult describing the change without touching the disk; `write_result`
performs it. JSON ops live in ops_json.py, file ops in ops_file.py, shared pieces in ops_base.py.
"""
import os

import ops_file
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


PREVIEWERS = {**ops_json.PREVIEWERS, **ops_file.PREVIEWERS}


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
    if r.mode is not None:
        os.chmod(r.path, r.mode)
