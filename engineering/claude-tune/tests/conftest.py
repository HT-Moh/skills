"""Fixtures for the claude-tune audit skill tests."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for d in (HERE.parent / "scripts", HERE.parent.parent / "claude-tune-apply" / "scripts"):
    sys.path.insert(0, str(d))
