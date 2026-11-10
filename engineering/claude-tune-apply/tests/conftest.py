"""Shared fixtures for the claude-tune-apply engine tests."""
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
APPLY_SCRIPTS = HERE.parent / "scripts"
TUNE_SCRIPTS = HERE.parent.parent / "claude-tune" / "scripts"
for d in (TUNE_SCRIPTS, APPLY_SCRIPTS):
    sys.path.insert(0, str(d))


@pytest.fixture
def scripts_dir() -> Path:
    return APPLY_SCRIPTS


@pytest.fixture
def tmp_home(tmp_path, monkeypatch) -> Path:
    """A fake HOME with the ~/.claude/tune/plans tree already created."""
    home = tmp_path / "home"
    (home / ".claude" / "tune" / "plans").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def plan_file(tmp_home):
    """Write a plan dict to ~/.claude/tune/plans/test.json and return its path."""
    def _write(plan: dict, name: str = "test.json") -> Path:
        path = tmp_home / ".claude" / "tune" / "plans" / name
        path.write_text(json.dumps(plan, indent=2))
        return path
    return _write
