"""File operations: create, append, replace, remove, symlink. Idempotent previews.

A file op may carry `sha256`: the target's hash at plan time. The preview refuses when the
live file differs. A symlink or directory target is refused for every kind except
`file_remove` of a symlink, which removes the link and records where it pointed.
"""
import hashlib
import os

from ops_base import OpResult, check_path, read_text, target_kind
from plan_schema import PlanError


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _guard_target(path, kind):
    tk = target_kind(path)
    if tk == "dir":
        raise ValueError(f"{path} is a directory")
    if tk in ("symlink", "dangling-symlink") and kind != "file_remove":
        raise ValueError(f"{path} is a symlink; use the symlink op or remove it first")
    return tk


def _check_sha256(op, before):
    if "sha256" in op and sha256_text(before) != op["sha256"]:
        raise ValueError("sha256 precondition failed: the file changed since the plan was written")


def _guarded(kind, op, path, overlay, build):
    """Run `build(before)` after the target-type and hash guards; guard failures become op errors."""
    try:
        _guard_target(path, kind)
        before = read_text(path, overlay)
        _check_sha256(op, before)
        return build(before)
    except (ValueError, PlanError) as exc:
        return OpResult(kind=kind, path=path, errors=[str(exc)])


def preview_file_create(op, path, overlay=None):
    content = op.get("content", "")

    def build(before):
        if before is not None and before != content:
            raise ValueError("file exists with different content; use file_replace or file_append")
        return OpResult(kind="file_create", path=path, before=before, after=content,
                        changed=before is None, mode=op.get("mode"))
    return _guarded("file_create", op, path, overlay, build)


def _lines(text):
    return [line for line in text.splitlines() if line.strip()]


def preview_file_append(op, path, overlay=None):
    content = op.get("content", "")
    if not content.strip():
        return OpResult(kind="file_append", path=path, errors=["file_append needs non-empty content"])

    def build(before):
        existing = set(_lines(before or ""))
        if before is not None and all(line in existing for line in _lines(content)):
            return OpResult(kind="file_append", path=path, before=before, after=before, note="already present")
        base = before or ""
        sep = "" if (not base or base.endswith("\n")) else "\n"
        return OpResult(kind="file_append", path=path, before=before, after=base + sep + content, changed=True)
    return _guarded("file_append", op, path, overlay, build)


def preview_file_replace(op, path, overlay=None):
    old, new = op.get("old", ""), op.get("new", "")

    def build(before):
        if before is None:
            raise ValueError("file does not exist")
        n = before.count(old)
        if n == 0 and (new == "" or new in before):
            return OpResult(kind="file_replace", path=path, before=before, after=before, note="already replaced")
        if n != 1:
            raise ValueError(f"old text occurs {n} times, need exactly 1")
        return OpResult(kind="file_replace", path=path, before=before, after=before.replace(old, new, 1), changed=True)
    return _guarded("file_replace", op, path, overlay, build)


def preview_file_remove(op, path, overlay=None):
    tk = target_kind(path)
    if tk == "dir":
        return OpResult(kind="file_remove", path=path, errors=[f"{path} is a directory"])
    if tk in ("symlink", "dangling-symlink"):
        return OpResult(kind="file_remove", path=path, after=None, changed=True,
                        symlink_target=os.readlink(path), summary_only=True)
    try:
        before = read_text(path, overlay)
        _check_sha256(op, before)
    except ValueError as exc:
        return OpResult(kind="file_remove", path=path, errors=[str(exc)])
    return OpResult(kind="file_remove", path=path, before=before, after=None,
                    changed=before is not None, summary_only=True)


def _resolve_target(link, target):
    base = target if os.path.isabs(target) else os.path.join(os.path.dirname(link), target)
    return os.path.realpath(os.path.expanduser(base))


def preview_symlink(op, path, overlay=None):
    target = op.get("target", "")
    if not target:
        return OpResult(kind="symlink", path=path, errors=["symlink needs target"])
    resolved = _resolve_target(path, target)
    r = OpResult(kind="symlink", path=path, symlink_target=target)
    try:
        check_path(resolved)
    except PlanError as exc:
        r.errors.append(f"symlink target refused: {exc}")
        return r
    if not os.path.exists(resolved):
        r.errors.append(f"symlink target does not exist: {resolved}")
    elif os.path.islink(path):
        if os.path.realpath(path) != resolved:
            r.errors.append(f"link exists and points to {os.readlink(path)}")
    elif os.path.lexists(path):
        r.errors.append("path exists and is not a symlink")
    else:
        r.changed = True
    return r


PREVIEWERS = {"file_create": preview_file_create, "file_append": preview_file_append,
              "file_replace": preview_file_replace, "symlink": preview_symlink,
              "file_remove": preview_file_remove}
