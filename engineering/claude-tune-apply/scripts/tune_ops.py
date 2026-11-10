"""Operations a tuning plan item can carry, and how each one previews or applies.

Every op is idempotent: applying it twice yields the same files. Each `preview_*`
returns an OpResult describing the change without touching the disk; `write_result`
performs it. Standard library only.
"""
import difflib, json, os
from dataclasses import dataclass, field

from plan_schema import OP_KINDS, PlanError
from redact import redact

SYSTEM_PREFIXES = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/boot", "/var", "/opt", "/root", "/sys",
                   "/proc", "/dev", "/tmp", "/run", "/srv", "/mnt")
# Relative to $HOME. Code that runs at login or on every shell, and credential stores.
REFUSED_USER_PATHS = (".bashrc", ".zshrc", ".zprofile", ".profile", ".bash_profile", ".ssh",
                      ".config/autostart", ".config/systemd", ".gnupg", ".aws", ".kube")
ALLOWED_USER_ROOTS = (".claude", ".agents", ".config/claude")
JSON_INDENT = 2


class ReadError(Exception):
    """A target could not be read as UTF-8 text (missing files are not errors)."""


@dataclass
class OpResult:
    kind: str
    path: str = ""
    before: str = None       # None = file did not exist
    after: str = None        # None = file removed (or symlink target)
    changed: bool = False
    note: str = ""
    symlink_target: str = ""
    manual_text: str = ""
    errors: list = field(default_factory=list)

    def diff(self):
        if self.kind == "manual":
            return self.manual_text
        if self.kind == "symlink":
            return f"{self.path} -> {self.symlink_target}"
        if not self.changed:
            return ""
        # Never print a credential value, even in a diff that deletes it.
        a = redact(self.before or "").splitlines(keepends=True)
        b = redact(self.after or "").splitlines(keepends=True)
        return "".join(difflib.unified_diff(a, b, f"a{self.path}", f"b{self.path}", n=2))


def expand(path):
    return os.path.realpath(os.path.expanduser(path))


def _home():
    return os.path.realpath(os.path.expanduser("~"))


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _in_git_worktree(real):
    """True for a file inside a repository, false for anything under its .git directory."""
    if ".git" in real.split("/"):
        return False
    probe = os.path.dirname(real)
    while probe and probe != "/":
        if os.path.isdir(os.path.join(probe, ".git")):
            return True
        probe = os.path.dirname(probe)
    return False


def check_path(path):
    """Return the real path a plan may touch, or raise PlanError saying why not."""
    real = expand(path)
    home = _home()
    if real == os.path.join(home, ".claude.json"):
        raise PlanError("~/.claude.json is rewritten by running sessions; use `claude mcp add/remove` or edit with all sessions closed")
    if any(_under(real, os.path.join(home, rel)) for rel in REFUSED_USER_PATHS):
        raise PlanError(f"login-time or credential path refused: {real}")
    if any(_under(real, os.path.join(home, rel)) for rel in ALLOWED_USER_ROOTS):
        return real  # checked before the system prefixes so a HOME under /tmp (tests) still works
    if _in_git_worktree(real):
        return real
    if any(_under(real, pre) for pre in SYSTEM_PREFIXES):
        raise PlanError(f"system path refused: {real}")
    raise PlanError(f"path outside ~/.claude, ~/.agents, ~/.config/claude or a git work tree: {real}")


def target_kind(path):
    """missing | file | symlink | dangling-symlink | dir, without following the final link."""
    if os.path.islink(path):
        return "symlink" if os.path.exists(path) else "dangling-symlink"
    if not os.path.lexists(path):
        return "missing"
    return "dir" if os.path.isdir(path) else "file"


def read_text(path, overlay=None):
    """Current text of `path` (None when missing), preferring the in-item overlay of earlier ops."""
    if overlay is not None and path in overlay:
        return overlay[path]
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise ReadError(f"cannot read {path}: {exc}") from exc


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


def _load_json(text, path):
    if text is None or not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} is not valid JSON: {exc}")


def _dump_json(obj):
    return json.dumps(obj, indent=JSON_INDENT, ensure_ascii=False) + "\n"


def _walk(obj, keys, create):
    for k in keys:
        if not isinstance(obj, dict):
            raise ValueError(f"path element {k!r} is not under an object")
        if k not in obj:
            if not create:
                return None
            obj[k] = {}
        obj = obj[k]
    return obj


def _json_result(op, path, mutate, overlay=None):
    before = read_text(path, overlay)
    try:
        doc = _load_json(before, path)
        mutate(doc)
    except ValueError as exc:
        return OpResult(kind=op["kind"], path=path, before=before, errors=[str(exc)])
    after = _dump_json(doc)
    unchanged = before is not None and json.loads(before) == doc
    return OpResult(kind=op["kind"], path=path, before=before, after=after, changed=not unchanged)


def preview_json_set(op, path, overlay=None):
    keys = list(op.get("path") or [])
    if not keys:
        return OpResult(kind="json_set", path=path, errors=["json_set needs a non-empty path"])

    def mutate(doc):
        _walk(doc, keys[:-1], create=True)[keys[-1]] = op.get("value")
    return _json_result(op, path, mutate, overlay)


def preview_json_delete(op, path, overlay=None):
    keys = list(op.get("path") or [])
    if not keys:
        return OpResult(kind="json_delete", path=path, errors=["json_delete needs a non-empty path"])

    def mutate(doc):
        parent = _walk(doc, keys[:-1], create=False)
        if isinstance(parent, dict):
            parent.pop(keys[-1], None)
    return _json_result(op, path, mutate, overlay)


def preview_json_append(op, path, overlay=None):
    keys = list(op.get("path") or [])
    values = list(op.get("values") or [])
    if not keys or not values:
        return OpResult(kind="json_append", path=path, errors=["json_append needs path and values"])

    def mutate(doc):
        parent = _walk(doc, keys[:-1], create=True)
        lst = parent.setdefault(keys[-1], [])
        if not isinstance(lst, list):
            raise ValueError(f"{'.'.join(keys)} is not a list")
        for v in values:
            if v not in lst:
                lst.append(v)
    return _json_result(op, path, mutate, overlay)


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
    "json_set": preview_json_set, "json_delete": preview_json_delete, "json_append": preview_json_append,
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
