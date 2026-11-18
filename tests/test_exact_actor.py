"""DOM ownership regressions for the installed SDUI actor adapter."""
from pathlib import Path
import subprocess


def test_actor_ownership():
    result = subprocess.run(["node", "--test", str(Path(__file__).with_name(
        "exact_actor.test.cjs"))], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
