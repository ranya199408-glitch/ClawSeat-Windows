from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_solo_dry_run_passes(tmp_path: Path) -> None:
    """install.sh --dry-run with clawseat-solo template exits 0."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "bash",
            "scripts/install.sh",
            "--dry-run",
            "--project",
            "test-solo",
            "--template",
            "clawseat-solo",
        ],
        cwd=_REPO,
        capture_output=True,
        text=True,
        timeout=60,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHON_BIN": sys.executable,
        },
        check=False,
    )
    assert result.returncode == 0, f"dry-run failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    output = result.stdout + result.stderr
    assert "CLAWSEAT_TEMPLATE_NAME=clawseat-solo" in output
    assert "PENDING_SEATS=(builder planner)" in output
