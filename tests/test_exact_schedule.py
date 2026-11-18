"""Offline native schedule action ordering regressions."""
from pathlib import Path
import subprocess


def test_exact_schedule_event_order():
    result = subprocess.run(
        ["node", "--test", str(Path(__file__).with_name("exact_schedule.test.cjs"))],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
