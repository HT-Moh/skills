"""Who reads a value a plan item deletes or replaces.

Greps key names across the places Claude Code configuration is consumed from: personal
skills, hooks, instruction files, the user config and the crontab. Returns file paths and
the key name only, never file content.
"""
import os
import subprocess
from pathlib import Path

SEARCH_ROOTS = (".agents/skills", ".claude/skills", ".claude/hooks", ".claude/CLAUDE.md", ".claude/rules")
TEXT_SUFFIXES = {".md", ".sh", ".py", ".js", ".mjs", ".json", ".yml", ".yaml", ".toml", ".txt", ".env", ""}
MAX_FILE_BYTES = 2_000_000
ROOT_ONLY_JSON_KEYS = ("permissions", "hooks", "env", "mcpServers")


def _crontab() -> str:
    try:
        return subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _candidate_files(roots):
    for root in roots:
        p = Path(root)
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and not f.is_symlink() and f.suffix in TEXT_SUFFIXES:
                    yield f


def _mentions(path: Path, names: list[str]) -> list[str]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [n for n in names if n in text]


def find_consumers(names: list[str], roots: list[str] | None = None) -> list[str]:
    """`<path>: <name>` lines for every file (and the crontab) that mentions a key name."""
    home = Path(os.path.expanduser("~"))
    search = [str(home / r) for r in SEARCH_ROOTS] + [str(home / ".claude.json")] if roots is None else roots
    out = []
    for path in _candidate_files(search):
        for name in _mentions(path, names):
            out.append(f"{path}: {name}")
    cron = _crontab()
    out += [f"crontab: {n}" for n in names if n in cron]
    return sorted(set(out))


def key_names_touched(item: dict) -> list[str]:
    """The last JSON key of every op under env, permissions, hooks or mcpServers."""
    names = []
    for op in item.get("ops") or []:
        path = op.get("path") if isinstance(op, dict) else None
        if isinstance(path, list) and path and str(path[0]) in ROOT_ONLY_JSON_KEYS and len(path) > 1:
            names.append(str(path[-1]))
    return names
