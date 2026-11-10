"""Structured checks a plan item carries: pre (before backup), post (after write), deferred.

A failing pre-check refuses the item before anything is touched. A failing post-check
rolls the item back. Deferred checks only print. `cmd_exit` runs an argv list, never a
shell, from a short allowlist, with a timeout.
"""
import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass

from plan_schema import CHECK_KINDS, PlanError

CMD_ALLOWLIST = ("claude", "test", "stat", "grep", "ls", "readlink")
DEFAULT_TIMEOUT_S = 10


@dataclass
class CheckResult:
    kind: str
    ok: bool
    detail: str


def _path(check: dict) -> str:
    return os.path.abspath(os.path.expanduser(str(check.get("file", ""))))


def _json_value(check: dict):
    """The value at check.path, or a sentinel string when the file or key is missing."""
    try:
        with open(_path(check), encoding="utf-8") as fh:
            node = json.load(fh)
        for k in check.get("path") or []:
            node = node[k]
        return node
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return _ABSENT


_ABSENT = object()


def _json_equals(check):
    current = _json_value(check)
    ok = current is not _ABSENT and current == check.get("value")
    return CheckResult("json_equals", ok, f"{'.'.join(check.get('path') or [])} {'matches' if ok else 'differs or absent'}")


def _json_absent(check):
    ok = _json_value(check) is _ABSENT
    return CheckResult("json_absent", ok, f"{'.'.join(check.get('path') or [])} {'absent' if ok else 'present'}")


def _file_contains(check):
    try:
        ok = str(check.get("text", "")) in open(_path(check), encoding="utf-8", errors="replace").read()
    except OSError:
        ok = False
    return CheckResult("file_contains", ok, f"{_path(check)} {'contains' if ok else 'lacks'} the text")


def _file_absent(check):
    ok = not os.path.lexists(_path(check))
    return CheckResult("file_absent", ok, f"{_path(check)} {'absent' if ok else 'exists'}")


def _file_sha256(check):
    try:
        digest = hashlib.sha256(open(_path(check), "rb").read()).hexdigest()
    except OSError:
        digest = ""
    ok = digest == check.get("sha256")
    return CheckResult("file_sha256", ok, f"{_path(check)} sha256 {'matches' if ok else 'differs'}")


def _file_mode(check):
    try:
        mode = stat.S_IMODE(os.stat(_path(check)).st_mode)
    except OSError:
        return CheckResult("file_mode", False, f"{_path(check)} missing")
    ok = mode == check.get("mode")
    return CheckResult("file_mode", ok, f"{_path(check)} mode {oct(mode)}")


def _cmd_exit(check):
    argv = [str(a) for a in check.get("argv") or []]
    if not argv or os.path.basename(argv[0]) not in CMD_ALLOWLIST:
        return CheckResult("cmd_exit", False, f"{argv[:1]} not in the allowlist {CMD_ALLOWLIST}")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=check.get("timeout_s", DEFAULT_TIMEOUT_S))
    except subprocess.TimeoutExpired:
        return CheckResult("cmd_exit", False, f"{' '.join(argv)} timed out")
    except OSError as exc:
        return CheckResult("cmd_exit", False, f"{' '.join(argv)} failed to start: {exc}")
    return CheckResult("cmd_exit", proc.returncode == 0, f"{' '.join(argv)} exited {proc.returncode}")


def _note(check):
    return CheckResult("note", True, str(check.get("text", "")))


RUNNERS = {"json_equals": _json_equals, "json_absent": _json_absent, "file_contains": _file_contains,
           "file_absent": _file_absent, "file_sha256": _file_sha256, "file_mode": _file_mode,
           "cmd_exit": _cmd_exit, "note": _note}
assert set(RUNNERS) == set(CHECK_KINDS)


def run_checks(item: dict, phase: str) -> list[CheckResult]:
    """Run the item's checks of one phase; unknown kinds fail rather than pass."""
    out = []
    for check in item.get("checks") or []:
        if check.get("phase") != phase:
            continue
        runner = RUNNERS.get(check.get("kind"))
        out.append(runner(check) if runner else CheckResult(str(check.get("kind")), False, "unknown check kind"))
    return out


def failures(item: dict, phase: str) -> list[str]:
    return [f"{phase}-check {r.kind} failed: {r.detail}" for r in run_checks(item, phase) if not r.ok]


def require_post(item: dict) -> None:
    """Raise PlanError when any post-check of the item fails (used by --done)."""
    failed = failures(item, "post")
    if failed:
        raise PlanError(f"{item['id']}: " + "; ".join(failed))
