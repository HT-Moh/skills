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


def preview_item_ops(ops, overlay=None):
    """Preview an item's ops in order; each op sees the text the previous one produced.

    Pass one `overlay` dict across items to chain a whole selection (the dry run does)."""
    overlay = {} if overlay is None else overlay
    results = []
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


class StaleTargetError(PlanError):
    """The target no longer matches the previewed `before` text, or is a symlink."""


def secure_umask():
    """New files and directories are owner-only from here on."""
    os.umask(0o077)


def _current_mode(path, fallback=0o600):
    try:
        return os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        return fallback


def atomic_write(path, data, mode):
    """Write `data` to a temp file beside `path`, never through a symlink, then replace."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, f".{os.path.basename(path)}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise


def _check_unchanged(r):
    if r.kind != "file_remove" and os.path.islink(r.path):
        raise StaleTargetError(f"{r.path} is a symlink; refusing to write through it")
    try:
        current = read_text(r.path)
    except ReadError as exc:
        raise StaleTargetError(str(exc)) from exc
    if current != r.before:
        raise StaleTargetError(f"{r.path} changed since the dry run; run --dry-run again")


def write_result(r):
    """Apply a previewed change. Caller has already backed the file up and re-checked the plan."""
    if not r.changed or r.errors or r.kind == "manual":
        return
    if r.kind == "symlink":
        os.makedirs(os.path.dirname(r.path), exist_ok=True)
        os.symlink(r.symlink_target, r.path)
        return
    if r.symlink_target and r.kind == "file_remove":
        os.remove(r.path)  # the link itself, never its target
        return
    _check_unchanged(r)
    if r.after is None:
        os.remove(r.path)
        return
    atomic_write(r.path, r.after, r.mode if r.mode is not None else _current_mode(r.path))
