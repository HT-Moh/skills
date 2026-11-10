"""Per-item backups under ~/.claude/tune/backups/<timestamp>_<id>/ with a manifest.

The manifest records, per touched path: kind, whether it existed, the saved copy name,
whether the parent directory existed, the mode, a symlink's target and the sha256 after
the write. Everything is owner-only (0700 directories, 0600 files).
"""
import datetime as dt
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

from plan_schema import PlanError
from redact import has_secret

DIR_MODE = 0o700
FILE_MODE = 0o600


def backup_root() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "tune" / "backups"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mkdir_private(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, DIR_MODE)


def _ensure_private_tree(bdir: Path) -> None:
    tune_dir = backup_root().parent
    for d in (tune_dir, backup_root(), bdir):
        _mkdir_private(d)


def _entry(n: int, r) -> dict:
    path = r.path
    existed = os.path.lexists(path)
    entry = {"path": path, "kind": r.kind, "existed": existed, "saved_as": "",
             "parent_existed": os.path.isdir(os.path.dirname(path)), "mode": None,
             "link_target": "", "sha256_after": ""}
    if existed:
        entry["mode"] = stat.S_IMODE(os.lstat(path).st_mode)
    if existed and os.path.islink(path):
        entry["link_target"] = os.readlink(path)
    elif existed and os.path.isfile(path):
        entry["saved_as"] = f"{n:02d}_{os.path.basename(path)}"
    return entry


def _save_copy(bdir: Path, entry: dict) -> None:
    if not entry["saved_as"]:
        return
    dest = bdir / entry["saved_as"]
    shutil.copyfile(entry["path"], dest)
    os.chmod(dest, FILE_MODE)


def _write_manifest(bdir: Path, manifest: dict) -> None:
    target = bdir / "manifest.json"
    target.write_text(json.dumps(manifest, indent=1))
    os.chmod(target, FILE_MODE)


def make_backup(item_id: str, results: list) -> Path:
    """Copy every file the results will touch into a fresh private directory; return it."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S.%f")
    bdir = backup_root() / f"{stamp}_{item_id}"
    _ensure_private_tree(bdir)
    manifest = {"item": item_id, "created": stamp, "files": [], "contains_secret": False}
    seen: set[str] = set()
    for n, r in enumerate(results):
        if not r.changed or r.kind == "manual" or r.path in seen:
            continue
        seen.add(r.path)
        entry = _entry(n, r)
        _save_copy(bdir, entry)
        manifest["files"].append(entry)
    manifest["contains_secret"] = any(
        f["saved_as"] and has_secret((bdir / f["saved_as"]).read_text(errors="replace")) for f in manifest["files"])
    _write_manifest(bdir, manifest)
    return bdir


def record_after_hashes(bdir: Path) -> None:
    """After the writes: store each surviving file's sha256 so rollback can detect drift."""
    manifest = load_manifest(bdir)
    for f in manifest["files"]:
        p = Path(f["path"])
        f["sha256_after"] = sha256_file(p) if p.is_file() and not p.is_symlink() else ""
    _write_manifest(bdir, manifest)


def backup_dir_for(item: dict) -> Path:
    """The item's backup directory, verified to live directly under the backup root."""
    recorded = item.get("backup")
    if not recorded:
        raise PlanError(f"{item.get('id')} has no backup recorded (status {item.get('status')})")
    bdir = Path(os.path.realpath(recorded))
    if bdir.parent != backup_root().resolve():
        raise PlanError(f"backup path {recorded} is not under {backup_root()}")
    return bdir


def load_manifest(bdir: Path) -> dict:
    """Read and sanity-check a manifest: saved copies are plain names, never paths."""
    manifest = json.loads((bdir / "manifest.json").read_text())
    for f in manifest.get("files", []):
        saved = f.get("saved_as", "")
        if saved and ("/" in saved or saved.startswith(".")):
            raise PlanError(f"manifest in {bdir} names an unsafe saved copy: {saved}")
    return manifest


def purge_backup(bdir: Path) -> None:
    """Delete a backup directory (and the secrets it holds). Rollback becomes impossible."""
    if bdir.resolve().parent != backup_root().resolve():
        raise PlanError(f"refusing to purge {bdir}: not a backup directory")
    shutil.rmtree(bdir)
