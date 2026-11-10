"""Load, validate, save and lock plan files under ~/.claude/tune/plans/.

A plan outside that directory is refused, as is a `latest.json` pointing outside it.
Saves are atomic and owner-only. One lock guards every load-modify-save.
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path

from plan_schema import PlanError, migrate_v1, validate

FILE_MODE = 0o600
DIR_MODE = 0o700


def plans_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "tune" / "plans"


def latest_path() -> Path:
    return plans_dir() / "latest.json"


def lock_path() -> Path:
    return plans_dir().parent / ".lock"


def _inside_plans_dir(path: Path) -> Path:
    real = Path(os.path.realpath(path))
    if real.parent != plans_dir().resolve():
        raise PlanError(f"{path} is not inside {plans_dir()}; plans live there only")
    return real


def load_plan(path: str | None) -> tuple[dict, Path]:
    """The plan (migrated to schema 2 and validated) and the file it came from."""
    chosen = Path(path) if path else latest_path()
    if not chosen.exists():
        raise PlanError(f"no plan at {chosen}. Run /claude-tune first.")
    real = _inside_plans_dir(chosen)
    with open(real, encoding="utf-8") as fh:
        plan = migrate_v1(json.load(fh))
    errors = validate(plan)
    if errors:
        raise PlanError("invalid plan:\n" + "\n".join("  " + e for e in errors))
    return plan, real  # the plan file itself, never the latest.json link


def save_plan(plan: dict, path: Path) -> None:
    """Write the plan atomically beside its path, owner-only."""
    real = _inside_plans_dir(path)
    tmp = real.with_name(f".{real.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=1, ensure_ascii=False)
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, real)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


@contextlib.contextmanager
def locked():
    """Hold ~/.claude/tune/.lock for the duration; a second holder blocks until release."""
    lock = lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    fd = os.open(lock, os.O_RDWR | os.O_CREAT, FILE_MODE)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _applied_ids(plan_path: Path) -> list[str]:
    try:
        with open(plan_path, encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, ValueError):
        return []
    return [it.get("id", "?") for it in plan.get("items", []) if isinstance(it, dict) and it.get("status") == "applied"]


def point_latest(path: Path, force: bool = False) -> None:
    """Make latest.json point at `path` without a moment where it is missing.

    Refuses when the current latest plan has applied items (their backups would be orphaned)
    unless `force`, which maps 1:1 to the CLI flag.
    """
    real = _inside_plans_dir(path)
    latest = latest_path()
    if latest.exists() and os.path.realpath(latest) != str(real) and not force:
        applied = _applied_ids(Path(os.path.realpath(latest)))
        if applied:
            raise PlanError(f"latest.json points at a plan with applied items ({', '.join(applied)}); "
                            f"roll them back or pass --force")
    tmp = latest.with_name(f".latest.{os.getpid()}.tmp")
    os.symlink(real, tmp)
    os.replace(tmp, latest)
