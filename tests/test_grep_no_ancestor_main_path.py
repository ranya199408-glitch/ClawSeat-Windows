from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_ancestor_main_path_hits_do_not_grow() -> None:
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "ancestor",
            "--",
            "core/scripts/install.sh",
            "core/scripts/agent_admin_*.py",
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    hits = [line for line in result.stdout.splitlines() if line.strip()]

    assert result.returncode in (0, 1), result.stderr
    assert len(hits) <= 6, "\n".join(hits)
