from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_warns_when_sandbox_home_differs() -> None:
    """detect_sandbox_home warns when HOME is not the real operator home."""
    script = f"""
HOME=/tmp/clawseat-sandbox-home
CLAWSEAT_REAL_HOME=/tmp/fake-home
source {REPO / 'scripts/install/lib/preflight.sh'}
detect_sandbox_home
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "sandbox HOME" in output
    assert "Use absolute paths" in output
