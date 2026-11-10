"""Structured checks a plan item carries: pre (before backup), post (after write), deferred.

A failing pre-check refuses the item before anything is touched. A failing post-check
rolls the item back. Deferred checks only print. `cmd_exit` is never executed by the
engine: its argv is validated against a short allowlist and shown to the user to run.
"""
import hashlib
import json
import os
import stat
from dataclasses import dataclass

from ops_base import check_path
from plan_schema import CHECK_KINDS, PlanError, cmd_form_error

MAX_READ_BYTES = 2_000_000


@dataclass
class CheckResult:
    kind: str
    ok: bool
    detail: str


def _path(check: dict) -> str:
    """The checked file, under the same path policy as the ops; raises PlanError when refused."""
    return check_path(str(check.get("file", "")))


def _read(path: str, mode: str = "r"):
    """Read a regular file of bounded size; anything else raises OSError."""
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise OSError(f"{path} is not a regular file")
    if st.st_size > MAX_READ_BYTES:
        raise OSError(f"{path} is larger than {MAX_READ_BYTES} bytes")
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8", "errors": "replace"})) as fh:
        return fh.read()


def _json_value(check: dict):
    """The value at check.path, or a sentinel when the file or key is missing."""
    try:
        node = json.loads(_read(_path(check)))
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
        ok = str(check.get("text", "")) in _read(_path(check))
    except OSError:
        ok = False
    return CheckResult("file_contains", ok, f"{_path(check)} {'contains' if ok else 'lacks'} the text")


def _file_absent(check):
    ok = not os.path.lexists(_path(check))
    return CheckResult("file_absent", ok, f"{_path(check)} {'absent' if ok else 'exists'}")


def _file_sha256(check):
    try:
        digest = hashlib.sha256(_read(_path(check), "rb")).hexdigest()
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
    """Validated and displayed only. Running plan-supplied commands is not worth the exposure."""
    argv = check.get("argv")
    err = cmd_form_error(argv)
    if err:
        return CheckResult("cmd_exit", False, err.replace("argv[0] must be a bare name", "argv[0] must be a bare allowlist name"))
    return CheckResult("cmd_exit", True, f"not run; run it yourself: {' '.join(argv)}")


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
        out.append(_run_one(check, phase))
    return out


def _run_one(check: dict, phase: str) -> CheckResult:
    kind = str(check.get("kind"))
    runner = RUNNERS.get(kind)
    if runner is None:
        return CheckResult(kind, False, "unknown check kind")
    try:
        result = runner(check)
    except PlanError as exc:
        return CheckResult(kind, False, f"refused: {exc}")
    except Exception as exc:  # a broken check must never pass silently
        return CheckResult(kind, False, f"check raised {type(exc).__name__}: {exc}")
    return result


def failures(item: dict, phase: str) -> list[str]:
    return [f"{phase}-check {r.kind} failed: {r.detail}" for r in run_checks(item, phase) if not r.ok]


def require_post(item: dict) -> None:
    """Raise PlanError when any post-check of the item fails (used by --done)."""
    failed = failures(item, "post")
    if failed:
        raise PlanError(f"{item['id']}: " + "; ".join(failed))
