from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _template_text(right_seats: list[str], fill_order: str | None) -> str:
    right = ", ".join(f'"{seat}"' for seat in right_seats)
    lines = [
        "[window_layout.workers_grid]",
        'left_main_seat = "planner"',
        f"right_seats = [{right}]",
    ]
    if fill_order is not None:
        lines.append(f'right_fill_order = "{fill_order}"')
    return "\n".join(lines) + "\n"


def _workers_payload(tmp_path: Path, right_seats: list[str], fill_order: str | None = "col-major") -> dict:
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
    result = subprocess.run(["bash", "-lc", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_workers_payload_col_major_default_recipes(tmp_path: Path) -> None:
    assert _workers_payload(tmp_path / "n3", ["builder", "patrol"])["recipe"] == [
        [0, True],
        [1, False],
    ]
    assert _workers_payload(tmp_path / "n4", ["builder", "patrol", "designer"])["recipe"] == [
        [0, True],
        [1, False],
        [2, False],
    ]
    assert _workers_payload(tmp_path / "n5", ["builder", "patrol", "designer", "reviewer"])["recipe"] == [
        [0, True],
        [1, False],
        [2, False],
        [3, False],
    ]
    assert _workers_payload(
        tmp_path / "n6",
        ["builder", "patrol", "designer", "reviewer", "creative"],
    )["recipe"] == [
        [0, True],
        [1, False],
        [2, False],
        [3, False],
        [4, False],
    ]


def test_workers_payload_missing_fill_order_defaults_to_col_major(tmp_path: Path) -> None:
    payload = _workers_payload(tmp_path, ["builder", "patrol", "designer"], fill_order=None)

    assert payload["recipe"] == [[0, True], [1, False], [2, False]]
    assert [pane["label"] for pane in payload["panes"]] == ["planner", "builder", "patrol", "designer"]
