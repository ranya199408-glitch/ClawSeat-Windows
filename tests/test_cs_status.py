"""Tests for cs_status.py — read-only operator observability CLI (T4 bundle-B).

Tests use tmp_path to construct synthetic tasks root / handoff dir, so they
run fully offline without touching real profile state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from cs_status import (
    _parse_task_blocks,
    _resolve_state,
    _fmt_table,
    _age_str,
    collect_rows,
    main,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_profile(tmp_path: Path, seats: list[str]) -> MagicMock:
    handoff_dir = tmp_path / "patrol" / "handoffs"
    handoff_dir.mkdir(parents=True)
    profile = MagicMock()
    profile.seats = seats
    profile.handoff_dir = handoff_dir
    profile.todo_path.side_effect = lambda s: tmp_path / s / "TODO.md"
    return profile


def _write_todo(tmp_path: Path, seat: str, entries: list[dict]) -> None:
    seat_dir = tmp_path / seat
    seat_dir.mkdir(parents=True, exist_ok=True)
    blocks = [f"# Queue: {seat}\n"]
    for e in entries:
        status = e.get("status", "pending")
        task_id = e["task_id"]
        cid = e.get("correlation_id", "")
        cid_line = f"\ncorrelation_id: {cid}" if cid else ""
        blocks.append(
            f"## [{status}] {task_id}\n"
            f"task_id: {task_id}\n"
            f"title: {e.get('title', 'Untitled')}\n"
            f"source: {e.get('source', 'planner')}\n"
            f"reply_to: {e.get('reply_to', 'planner')}\n"
            f"dispatched_at: {e.get('dispatched_at', '2026-04-19T00:00:00+00:00')}"
            f"{cid_line}\n\n"
            f"### Objective\n\nDo things.\n"
        )
    (tmp_path / seat / "TODO.md").write_text("\n---\n".join(blocks))


def _write_receipt(handoff_dir: Path, data: dict) -> None:
    safe = lambda s: s.replace("-", "-")
    task_id = data["task_id"]
    source = data["source"]
    target = data["target"]
    fname = f"{task_id}__{source}__{target}.json"
    (handoff_dir / fname).write_text(json.dumps(data))


# ── _parse_task_blocks ────────────────────────────────────────────────────────


def test_parse_task_blocks_pending(tmp_path):
    """Pending entry is parsed correctly."""
    text = (
        "# Queue: builder-1\n\n"
        "## [pending] task-abc\n"
        "task_id: task-abc\n"
        "title: My task\n"
        "source: planner\n"
        "dispatched_at: 2026-04-19T10:00:00+00:00\n"
        "correlation_id: aabb1122\n\n"
        "### Objective\n\nDo it.\n"
    )
    blocks = _parse_task_blocks(text)
    assert len(blocks) == 1
    assert blocks[0]["task_id"] == "task-abc"
    assert blocks[0]["status"] == "pending"
    assert blocks[0]["correlation_id"] == "aabb1122"


def test_parse_task_blocks_skips_completed():
    """Completed blocks are parsed but have status=completed."""
    text = (
        "# Queue: builder-1\n\n"
        "## [completed] task-old\n"
        "task_id: task-old\n\n"
        "### Objective\nDone.\n"
    )
    blocks = _parse_task_blocks(text)
    assert blocks[0]["status"] == "completed"


# ── _resolve_state ────────────────────────────────────────────────────────────


def test_resolve_state_queued_no_receipts():
    """No receipts → queued."""
    state = _resolve_state("task-1", "builder-1", [])
    assert state == "queued"


def test_resolve_state_in_flight_dispatch_exists():
    """Dispatch receipt present, no completion → in-flight."""
    receipts = [{"kind": "dispatch", "task_id": "task-1", "source": "planner", "target": "builder-1"}]
    state = _resolve_state("task-1", "builder-1", receipts)
    assert state == "in-flight"


def test_resolve_state_delivered_completion_exists():
    """Completion receipt present → delivered."""
    receipts = [
        {"kind": "dispatch", "task_id": "task-1", "source": "planner", "target": "builder-1"},
        {"kind": "completion", "task_id": "task-1", "source": "builder-1", "target": "planner"},
    ]
    state = _resolve_state("task-1", "builder-1", receipts)
    assert state == "delivered"


# ── collect_rows ──────────────────────────────────────────────────────────────


def test_collect_rows_lists_active_tasks(tmp_path):
    """collect_rows returns rows for pending/queued tasks."""
    profile = _make_profile(tmp_path, ["builder-1", "reviewer-1"])
    _write_todo(tmp_path, "builder-1", [
        {"task_id": "task-a", "correlation_id": "aabb1122"},
    ])
    _write_todo(tmp_path, "reviewer-1", [
        {"task_id": "task-b", "correlation_id": "ccdd3344"},
    ])
    rows = collect_rows(profile)
    assert len(rows) == 2
    seats = {r["seat"] for r in rows}
    assert seats == {"builder-1", "reviewer-1"}


def test_collect_rows_seat_filter(tmp_path):
    """--seat filter narrows to one seat only."""
    profile = _make_profile(tmp_path, ["builder-1", "reviewer-1"])
    _write_todo(tmp_path, "builder-1", [{"task_id": "task-a"}])
    _write_todo(tmp_path, "reviewer-1", [{"task_id": "task-b"}])
    rows = collect_rows(profile, seat_filter="builder-1")
    assert len(rows) == 1
    assert rows[0]["seat"] == "builder-1"


def test_collect_rows_correlation_id_filter(tmp_path):
    """--correlation-id filter returns exactly matching row."""
    profile = _make_profile(tmp_path, ["builder-1"])
    _write_todo(tmp_path, "builder-1", [
        {"task_id": "task-a", "correlation_id": "aabb1122"},
        {"task_id": "task-b", "correlation_id": "ccdd3344"},
    ])
    rows = collect_rows(profile, cid_filter="aabb1122")
    assert len(rows) == 1
    assert rows[0]["task_id"] == "task-a"


def test_collect_rows_empty_tasks_root(tmp_path):
    """No TODO.md files → empty list, no crash."""
    profile = _make_profile(tmp_path, ["builder-1"])
    rows = collect_rows(profile)
    assert rows == []


def test_collect_rows_missing_correlation_id_renders_dash(tmp_path):
    """Legacy entry without correlation_id does not crash — renders '-'."""
    profile = _make_profile(tmp_path, ["builder-1"])
    _write_todo(tmp_path, "builder-1", [
        {"task_id": "legacy-task"},  # no correlation_id
    ])
    rows = collect_rows(profile)
    assert len(rows) == 1
    assert rows[0]["correlation_id"] == "-"


def test_collect_rows_state_classification(tmp_path):
    """State is correctly classified based on receipt evidence."""
    profile = _make_profile(tmp_path, ["builder-1"])
    _write_todo(tmp_path, "builder-1", [
        {"task_id": "task-inflight"},
    ])
    _write_receipt(profile.handoff_dir, {
        "kind": "dispatch", "task_id": "task-inflight",
        "source": "planner", "target": "builder-1",
    })
    rows = collect_rows(profile)
    assert rows[0]["state"] == "in-flight"


# ── _fmt_table ────────────────────────────────────────────────────────────────


def test_fmt_table_empty():
    assert _fmt_table([]) == "(no active tasks)"


def test_fmt_table_nonempty():
    rows = [{"seat": "builder-1", "task_id": "task-a", "correlation_id": "aabb1122",
             "state": "queued", "dispatched_at": "2026-04-19T00:00:00+00:00", "age": "5m",
             "title": "Test", "source": "planner", "target": "builder-1"}]
    table = _fmt_table(rows)
    assert "builder-1" in table
    assert "task-a" in table
    assert "aabb1122" in table
    assert "queued" in table


# ── JSON output (via main with monkeypatch) ───────────────────────────────────


def test_main_json_output(tmp_path, monkeypatch, capsys):
    """--json flag emits valid JSON parseable by json.loads."""
    profile = _make_profile(tmp_path, ["builder-1"])
    _write_todo(tmp_path, "builder-1", [
        {"task_id": "task-z", "correlation_id": "deadbeef"},
    ])
    monkeypatch.setattr("sys.argv", [
        "cs_status.py", "--profile", "dummy", "--json",
    ])

    import cs_status
    monkeypatch.setattr(cs_status, "load_profile", lambda _: profile)

    exit_code = main()
    out = capsys.readouterr().out
    data = json.loads(out)
    assert isinstance(data, list)
    assert data[0]["task_id"] == "task-z"
    assert exit_code == 0


def test_json_output_legacy_entry_has_null_correlation_id(tmp_path, monkeypatch, capsys):
    """JSON output maps missing correlation_id to null, not the string '-'."""
    profile = _make_profile(tmp_path, ["builder-1"])
    _write_todo(tmp_path, "builder-1", [
        {"task_id": "legacy-task"},  # no correlation_id field
    ])
    monkeypatch.setattr("sys.argv", ["cs_status.py", "--profile", "dummy", "--json"])
    import cs_status
    monkeypatch.setattr(cs_status, "load_profile", lambda _: profile)

    main()
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["correlation_id"] is None, f"expected null, got {data[0]['correlation_id']!r}"


def test_help_flag_succeeds(tmp_path):
    """subprocess --help exits 0 and prints usage — guards against import regressions."""
    import subprocess
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "cs_status.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()
