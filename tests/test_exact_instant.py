"""Current native state and committed-composer ownership contracts."""
from pathlib import Path
import subprocess


def test_current_instant_contract():
    root = Path(__file__).parents[1]
    result = subprocess.run(
        ["node", "--test", str(root / "tests/exact_instant.test.cjs")],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
