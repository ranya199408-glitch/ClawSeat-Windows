from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _workers_payload(tmp_path: Path, right_seats: list[str]) -> dict:
    templates = tmp_path / "templates"
    templates.mkdir(parents=True)
    right = ", ".join(f'"{seat}"' for seat in right_seats)
    (templates / "test.toml").write_text(
        "[window_layout.workers_grid]\n"
        'left_main_seat = "planner"\n'
        f"right_seats = [{right}]\n"
        'right_fill_order = "grid-2-rows"\n',
        encoding="utf-8",
    )
    seats_expr = " ".join(shlex.quote(seat) for seat in ["planner", *right_seats])
    script = f"""
set -euo pipefail
source {shlex.quote(str(_REPO / "scripts" / "install" / "lib" / "window.sh"))}
PROJECT=testproj
WAIT_FOR_SEAT_SCRIPT=/tmp/wait-for-seat.sh
REPO_ROOT={shlex.quote(str(tmp_path))}
CLAWSEAT_TEMPLATE_NAME=test
PYTHON_BIN={shlex.quote(sys.executable)}
PENDING_SEATS=({seats_expr})
workers_payload
"""
    result = subprocess.run(["bash", "-lc", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_workers_payload_grid_2_rows_preserves_legacy_recipes(tmp_path: Path) -> None:
    n3 = _workers_payload(tmp_path / "n3", ["builder", "patrol"])
    n4 = _workers_payload(tmp_path / "n4", ["builder", "patrol", "designer"])

    assert n3["recipe"] == [[0, True], [1, False]]
    assert [pane["label"] for pane in n3["panes"]] == ["planner", "builder", "patrol"]
    assert n4["recipe"] == [[0, True], [1, True], [1, False]]
    assert [pane["label"] for pane in n4["panes"]] == ["planner", "builder", "designer", "patrol"]
