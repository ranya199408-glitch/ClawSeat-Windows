from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_workers_payload_unknown_fill_order_fails(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "test.toml").write_text(
        "[window_layout.workers_grid]\n"
        'left_main_seat = "planner"\n'
        'right_seats = ["builder"]\n'
        'right_fill_order = "diagonal"\n',
        encoding="utf-8",
    )
    script = f"""
set -euo pipefail
source {shlex.quote(str(_REPO / "scripts" / "install" / "lib" / "window.sh"))}
PROJECT=testproj
WAIT_FOR_SEAT_SCRIPT=/tmp/wait-for-seat.sh
REPO_ROOT={shlex.quote(str(tmp_path))}
CLAWSEAT_TEMPLATE_NAME=test
PYTHON_BIN={shlex.quote(sys.executable)}
PENDING_SEATS=(planner builder)
workers_payload
"""
    result = subprocess.run(["bash", "-lc", script], capture_output=True, text=True, check=False)

    assert result.returncode != 0
    assert "unknown right_fill_order" in result.stderr
    assert "diagonal" in result.stderr
