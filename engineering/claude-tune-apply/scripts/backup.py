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


def _state_of(path: str) -> tuple:
    """(kind, detail) of what is on disk now: ('link', target), ('file', sha256) or ('missing', '')."""
    if os.path.islink(path):
        return "link", os.readlink(path)
    if os.path.isfile(path):
        return "file", sha256_file(Path(path))
    return "missing", ""


def record_after_hashes(bdir: Path) -> None:
    """After the writes: store what each path became, so rollback can detect drift."""
    manifest = load_manifest(bdir)
    for f in manifest["files"]:
        kind, detail = _state_of(f["path"])
        f["after_kind"] = kind
        f["sha256_after"] = detail if kind == "file" else ""
        f["link_target_after"] = detail if kind == "link" else ""
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


def dependents_of(plan: dict, item_id: str) -> list[str]:
    """Ids of items that depend on `item_id`, directly or through other items, in plan order."""
    found: list[str] = []
    frontier = {item_id}
    while frontier:
        new = {it["id"] for it in plan["items"]
               if it["id"] not in found and frontier & set(it.get("depends_on") or [])}
        found += sorted(new)
        frontier = new
    return found


def _drift(manifest: dict) -> list[str]:
    """Paths that no longer match what apply left behind. Unknown after-state counts as drift."""
    out = []
    for f in manifest["files"]:
        kind, detail = _state_of(f["path"])
        expected_kind = f.get("after_kind")
        if expected_kind is None:
            if kind != "missing":
                out.append(f["path"])  # old manifest: nothing recorded, fail closed
            continue
        expected_detail = f.get("sha256_after") if kind == "file" else f.get("link_target_after", "")
        if kind != expected_kind or (kind != "missing" and detail != expected_detail):
            out.append(f["path"])
    return out


def _checked_mode(f: dict) -> int:
    mode = f.get("mode")
    if mode is None:
        return FILE_MODE
    if isinstance(mode, bool) or not isinstance(mode, int):
        raise PlanError(f"manifest mode for {f['path']} is not an int")
    return mode & 0o777  # the file's own former mode, special bits dropped


def _write_bytes_atomic(path: str, data: bytes, mode: int) -> None:
    tmp = f"{path}.{os.getpid()}.restore"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, FILE_MODE)
    try:
        os.write(fd, data)
        os.fchmod(fd, mode)
        os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.remove(tmp)
        raise


def _validate_entry(f: dict) -> None:
    """Manifest paths are absolute and allowed; link targets resolve to allowed places too."""
    from ops_base import check_path
    path = f.get("path", "")
    if not os.path.isabs(path) or os.path.normpath(path) != path:
        raise PlanError(f"manifest path is not a normalised absolute path: {path!r}")
    f["path"] = check_path(path)
    _checked_mode(f)
    target = f.get("link_target")
    if target:
        resolved = target if os.path.isabs(target) else os.path.join(os.path.dirname(path), target)
        check_path(os.path.normpath(resolved))


def _restore_entry(bdir: Path, f: dict) -> None:
    path = f["path"]
    if f["existed"] and f.get("link_target"):
        if os.path.lexists(path):
            os.remove(path)
        os.symlink(f["link_target"], path)
    elif f["existed"] and f["saved_as"]:
        _write_bytes_atomic(path, (bdir / f["saved_as"]).read_bytes(), _checked_mode(f))
    elif not f["existed"] and os.path.lexists(path):
        os.remove(path)
        if not f.get("parent_existed", True):
            _rmdir_if_empty(os.path.dirname(path))


def _rmdir_if_empty(directory: str) -> None:
    try:
        os.rmdir(directory)
    except OSError:
        pass


def restore_from(bdir: Path, only=None) -> None:
    """Put files back as they were before the item wrote; `only` limits it to the paths written."""
    manifest = load_manifest(bdir)
    entries = [f for f in manifest["files"] if only is None or f["path"] in only]
    for f in entries:
        _validate_entry(f)
    for f in entries:
        _restore_entry(bdir, f)


def rollback_item(plan: dict, item: dict, force: bool = False) -> list[str]:
    """Restore every file of an applied item from its backup; return warning lines.

    `force` maps 1:1 to the CLI flag: without it, a file edited after apply stops the rollback.
    """
    if item.get("status") != "applied":
        raise PlanError(f"{item['id']} is {item.get('status')}; only applied items roll back")
    by_id = {it["id"]: it for it in plan["items"]}
    dependents = dependents_of(plan, item["id"])
    still_applied = [d for d in dependents if by_id[d].get("status") == "applied"]
    if still_applied:
        raise PlanError(f"{', '.join(still_applied)} depend on {item['id']} and are still applied; roll them back first")
    bdir = backup_dir_for(item)
    manifest = load_manifest(bdir)
    for f in manifest["files"]:
        _validate_entry(f)
    drift = _drift(manifest)
    if drift and not force:
        raise PlanError(f"{', '.join(drift)} changed after apply; roll back anyway with --force")
    warnings = [f"WARNING {p} was edited after apply (drift); the edit is overwritten" for p in drift]
    for f in manifest["files"]:
        _restore_entry(bdir, f)
    item["status"] = "rolled_back"
    for dep_id in dependents:
        by_id[dep_id]["status"] = "proposed"
        by_id[dep_id].pop("done_at", None)
        warnings.append(f"WARNING {dep_id} depended on {item['id']}; reset to proposed. Redo it with /claude-tune-apply {dep_id}")
    return warnings
