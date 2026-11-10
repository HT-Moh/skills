"""Shared ground for every op: the result record, path safety and text reading."""
import difflib
import hashlib
import os
from dataclasses import dataclass, field

from plan_schema import PlanError
from redact import redact

SYSTEM_PREFIXES = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/boot", "/var", "/opt", "/root", "/sys",
                   "/proc", "/dev", "/run", "/srv", "/mnt")
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
    mode: int = None         # file_create: mode to set after writing
    summary_only: bool = False  # file_remove: never print the content, only size and hash

    def diff(self):
        if self.kind == "manual":
            return self.manual_text
        if self.kind == "symlink":
            return f"{self.path} -> {self.symlink_target}"
        if not self.changed:
            return ""
        if self.summary_only:
            return self._summary()
        # Never print a credential value, even in a diff that deletes it.
        a = redact(self.before or "").splitlines(keepends=True)
        b = redact(self.after or "").splitlines(keepends=True)
        return "".join(difflib.unified_diff(a, b, f"a{self.path}", f"b{self.path}", n=2))

    def _summary(self):
        if self.symlink_target:
            return f"removes symlink {self.path} -> {self.symlink_target}"
        text = self.before or ""
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return f"removes {self.path}: {len(text.splitlines())} line(s), sha256 {digest}"


def expand(path):
    return os.path.realpath(os.path.expanduser(path))


def _home():
    return os.path.realpath(os.path.expanduser("~"))


def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def _in_git_worktree(real):
    """True for a file inside a repository whose root is neither $HOME nor a dot-directory."""
    home = _home()
    probe = os.path.dirname(real)
    while probe and probe != "/":
        if os.path.isdir(os.path.join(probe, ".git")):
            if not _under(probe, home):
                return True  # a repo outside $HOME (system prefixes were refused already)
            rel = os.path.relpath(probe, home)
            return rel != "." and not rel.startswith(".")  # not $HOME itself, not under a dot-dir
        probe = os.path.dirname(probe)
    return False


def check_path(path):
    """Return the absolute (unresolved) path a plan may touch, or raise PlanError saying why not.

    The link location and, when it resolves, the link target are both validated, so ops see
    the symlink itself and can refuse or remove it while nothing reaches a forbidden file.
    """
    lexical = os.path.abspath(os.path.expanduser(path))
    if os.path.islink(lexical):
        _validate_real(os.path.join(os.path.realpath(os.path.dirname(lexical)), os.path.basename(lexical)))
        if os.path.exists(lexical):
            _validate_real(os.path.realpath(lexical))
    else:
        _validate_real(os.path.realpath(lexical))
    return lexical


def _validate_real(real):
    home = _home()
    if any(part.casefold() == ".git" for part in real.split("/")):
        raise PlanError(f"git metadata refused: {real}")
    if real == os.path.join(home, ".claude.json"):
        raise PlanError("~/.claude.json is rewritten by running sessions; use `claude mcp add/remove` or edit with all sessions closed")
    if any(_under(real, os.path.join(home, rel)) for rel in REFUSED_USER_PATHS):
        raise PlanError(f"login-time or credential path refused: {real}")
    if any(_under(real, os.path.join(home, rel)) for rel in ALLOWED_USER_ROOTS):
        return
    if any(_under(real, pre) for pre in SYSTEM_PREFIXES):
        raise PlanError(f"system path refused: {real}")
    if _in_git_worktree(real):
        return
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
