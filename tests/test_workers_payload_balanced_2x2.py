from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _template_text(right_seats: list[str], fill_order: str) -> str:
    right = ", ".join(f'"{seat}"' for seat in right_seats)
    return (
        "[window_layout.workers_grid]\n"
        'left_main_seat = "planner"\n'
        f"right_seats = [{right}]\n"
        f'right_fill_order = "{fill_order}"\n'
    )


def _run_workers_payload(
    tmp_path: Path, right_seats: list[str], fill_order: str
) -> subprocess.CompletedProcess[str]:
    templates = tmp_path / "templates"
    templates.mkdir(parents=True)
    (templates / "test.toml").write_text(_template_text(right_seats, fill_order), encoding="utf-8")
    seats = ["planner", *right_seats]
    seats_expr = " ".join(shlex.quote(seat) for seat in seats)
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
    return subprocess.run(["bash", "-lc", script], capture_output=True, text=True, check=False)


def test_balanced_2x2_emits_driver_default_recipe(tmp_path: Path) -> None:
    """4-worker (main + 3 right) balanced-2x2 must produce equal 2x2 grid
    matching driver _LAYOUT_RECIPES[4] = [[0,True], [0,False], [1,False]].
    Pane order: planner=TL, builder=TR, patrol=BL, designer=BR."""
    result = _run_workers_payload(
        tmp_path, ["builder", "patrol", "designer"], "balanced-2x2"
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["recipe"] == [[0, True], [0, False], [1, False]]
    labels = [pane["label"] for pane in payload["panes"]]
    assert labels == ["planner", "builder", "patrol", "designer"]


def test_balanced_2x2_rejects_n_right_2(tmp_path: Path) -> None:
    """3-worker layouts must fall back to col-major or grid-2-rows."""
    result = _run_workers_payload(tmp_path, ["builder", "patrol"], "balanced-2x2")
    assert result.returncode != 0
    assert "balanced-2x2 requires exactly 3 right_seats" in result.stderr


def test_balanced_2x2_rejects_n_right_4(tmp_path: Path) -> None:
    """5-worker layouts (engineering template) must use col-major or grid-2-rows."""
    result = _run_workers_payload(
        tmp_path, ["builder", "reviewer", "patrol", "designer"], "balanced-2x2"
    )
    assert result.returncode != 0
    assert "balanced-2x2 requires exactly 3 right_seats" in result.stderr
