"""Tests for core/scripts/feishu_announcer.py — C11 feishu-announcer.

All tests use tmp_path / CLAWSEAT_STATE_DB so ~/.agents/state.db is never touched.
_feishu.send_feishu_user_message is always mocked (lark-cli is in needs_refresh).

Also covers T5/T6/T7 gap tests (cycle-31 findings):
  T5 — run_watch() daemon in events_watcher.py (untested until now)
  T6 — record_event_if_new empty fingerprint raises ValueError
  T7 — build_parser() defaults and mutual exclusion in events_watcher.py
"""
from __future__ import annotations

import json
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.lib.state import (
    Event,
    list_unsent_feishu_events,
    mark_feishu_sent,
    open_db,
    record_event,
    record_event_if_new,
)
import core.scripts.feishu_announcer as announcer
from core.scripts import events_watcher as watcher

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = open_db(db_path=tmp_path / "state.db")
    yield conn
    conn.close()


def _make_event(
    conn: sqlite3.Connection,
    *,
    type: str = "task.completed",
    project: str = "install",
    task_id: str = "C11",
    source: str = "builder-1",
    target: str = "planner",
    disposition: str = "AUTO_ADVANCE",
    lane: str = "planning",
    human_summary: str | None = None,
    feishu_sent: str | None = None,
    payload_extra: dict[str, object] | None = None,
) -> int:
    payload = dict(
        task_id=task_id, source=source, target=target,
        disposition=disposition, lane=lane,
    )
    if human_summary is not None:
        payload["human_summary"] = human_summary
    if payload_extra is not None:
        payload.update(payload_extra)
    conn.execute(
        "INSERT INTO events (ts, type, project, payload_json, feishu_sent) "
        "VALUES (datetime('now'), ?, ?, ?, ?)",
        (type, project, json.dumps(payload), feishu_sent),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


_PATCH_TARGET = "core.scripts.feishu_announcer.send_feishu_user_message"


def _sent_mock() -> MagicMock:
    m = MagicMock(return_value={"status": "sent"})
    return m


def _failed_mock() -> MagicMock:
    return MagicMock(return_value={"status": "failed", "reason": "auth expired"})


# ---------------------------------------------------------------------------
# Derivation helpers — pure unit tests
# ---------------------------------------------------------------------------

def test_derive_lane_valid():
    assert announcer._derive_lane({"lane": "builder"}) == "builder"


def test_derive_lane_invalid_falls_back_to_planning():
    assert announcer._derive_lane({"lane": "unknown_lane"}) == "planning"


def test_derive_lane_missing_falls_back_to_planning():
    assert announcer._derive_lane({}) == "planning"


def test_derive_lane_validated_against_feishu_set(monkeypatch):
    import _feishu
    for lane in _feishu.VALID_DELEGATION_LANES:
        assert announcer._derive_lane({"lane": lane}) == lane


def test_derive_report_status_task_completed():
    assert announcer._derive_report_status("task.completed", {}) == "done"


def test_derive_report_status_chain_closeout():
    assert announcer._derive_report_status("chain.closeout", {}) == "done"


def test_derive_report_status_unknown():
    assert announcer._derive_report_status("other.event", {}) == "in_progress"


def test_derive_decision_hint_user_decision_needed():
    assert announcer._derive_decision_hint({"disposition": "USER_DECISION_NEEDED"}) == "ask_user"


def test_derive_decision_hint_auto_advance():
    assert announcer._derive_decision_hint({"disposition": "AUTO_ADVANCE"}) == "proceed"


def test_derive_decision_hint_missing():
    assert announcer._derive_decision_hint({}) == "proceed"


def test_derive_user_gate_required():
    assert announcer._derive_user_gate({"disposition": "USER_DECISION_NEEDED"}) == "required"


def test_derive_user_gate_none_on_auto_advance():
    assert announcer._derive_user_gate({"disposition": "AUTO_ADVANCE"}) == "none"


def test_derive_user_gate_none_on_missing():
    assert announcer._derive_user_gate({}) == "none"


def test_derive_next_action_task_completed():
    assert announcer._derive_next_action("task.completed", {}) == "consume_closeout"


def test_derive_next_action_chain_closeout():
    assert announcer._derive_next_action("chain.closeout", {}) == "finalize_chain"


def test_derive_next_action_unknown():
    assert announcer._derive_next_action("weird.event", {}) == "wait"


def test_derive_summary_task_completed():
    payload = {"task_id": "C11", "source": "builder-1", "target": "planner"}
    s = announcer._derive_summary("task.completed", payload)
    assert "C11" in s and "builder-1" in s and "planner" in s


def test_derive_summary_chain_closeout():
    payload = {"task_id": "C11", "source": "planner"}
    s = announcer._derive_summary("chain.closeout", payload)
    assert "closeout" in s.lower() and "C11" in s


def test_derive_summary_unknown_event_type():
    s = announcer._derive_summary("weird.event", {"task_id": "X"})
    assert "weird.event" in s and "X" in s


# ---------------------------------------------------------------------------
# build_envelope — smoke
# ---------------------------------------------------------------------------

def test_build_envelope_returns_string(db):
    eid = _make_event(db)
    row = db.execute("SELECT id, ts, type, project, payload_json FROM events WHERE id=?",
                     (eid,)).fetchone()
    event = Event(id=row[0], ts=row[1], type=row[2], project=row[3], payload_json=row[4])
    result = announcer.build_envelope(event)
    assert isinstance(result, str) and len(result) > 0


# ---------------------------------------------------------------------------
# process_once — core cases
# ---------------------------------------------------------------------------

def test_unseen_task_completed_sent_and_marked(db):
    eid = _make_event(db)
    with patch(_PATCH_TARGET, _sent_mock()):
        counts = announcer.process_once(conn=db)
    assert counts["sent"] == 1 and counts["failed"] == 0
    ts = db.execute(
        "SELECT feishu_sent FROM events WHERE id=?", (eid,)
    ).fetchone()[0]
    assert ts is not None


def test_unseen_chain_closeout_sent_and_marked(db):
    eid = _make_event(db, type="chain.closeout")
    with patch(_PATCH_TARGET, _sent_mock()):
        counts = announcer.process_once(conn=db)
    assert counts["sent"] == 1
    ts = db.execute("SELECT feishu_sent FROM events WHERE id=?", (eid,)).fetchone()[0]
    assert ts is not None


def test_inline_sent_event_is_not_resent(db):
    eid = _make_event(
        db,
        type="chain.closeout",
        payload_extra={"feishu_already_sent": True},
        feishu_sent="2026-05-18T00:00:00+00:00",
    )
    mock = _sent_mock()

    with patch(_PATCH_TARGET, mock):
        counts = announcer.process_once(conn=db)

    mock.assert_not_called()
    assert counts["pending"] == 0
    assert counts["retrying"] == 0
    ts = db.execute("SELECT feishu_sent FROM events WHERE id=?", (eid,)).fetchone()[0]
    assert ts is not None


def test_already_sent_event_is_skipped(db):
    _make_event(db, feishu_sent="2026-04-21T00:00:00")
    mock = _sent_mock()
    with patch(_PATCH_TARGET, mock):
        counts = announcer.process_once(conn=db)
    assert counts["pending"] == 0
    mock.assert_not_called()


def test_mixed_batch_three_unseen_two_seen(db):
    for i in range(3):
        _make_event(db, task_id=f"C{i}")
    for i in range(3, 5):
        _make_event(db, task_id=f"C{i}", feishu_sent="2026-04-21T00:00:00")
    with patch(_PATCH_TARGET, _sent_mock()):
        counts = announcer.process_once(conn=db)
    assert counts["sent"] == 3 and counts["pending"] == 3


def test_send_returns_failed_feishu_sent_stays_null(db):
    eid = _make_event(db)
    with patch(_PATCH_TARGET, _failed_mock()):
        counts = announcer.process_once(conn=db)
    assert counts["failed"] == 1
    ts = db.execute("SELECT feishu_sent FROM events WHERE id=?", (eid,)).fetchone()[0]
    assert ts is None


def test_send_returns_failed_retrying_count(db):
    _make_event(db, task_id="C1")
    _make_event(db, task_id="C2")
    with patch(_PATCH_TARGET, _failed_mock()):
        counts = announcer.process_once(conn=db)
    assert counts["retrying"] == 2


def test_send_raises_exception_loop_continues_and_feishu_sent_null(db):
    eid1 = _make_event(db, task_id="C1")
    eid2 = _make_event(db, task_id="C2")
    call_count = 0

    def raiser(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("lark-cli crashed")
        return {"status": "sent"}

    with patch(_PATCH_TARGET, raiser):
        counts = announcer.process_once(conn=db)

    assert counts["sent"] == 1 and counts["failed"] == 1
    assert db.execute(
        "SELECT feishu_sent FROM events WHERE id=?", (eid1,)
    ).fetchone()[0] is None
    assert db.execute(
        "SELECT feishu_sent FROM events WHERE id=?", (eid2,)
    ).fetchone()[0] is not None


def test_dry_run_prints_envelope_no_db_write_no_real_send(db, capsys):
    eid = _make_event(db)
    mock = _sent_mock()
    with patch(_PATCH_TARGET, mock):
        counts = announcer.process_once(conn=db, dry_run=True)
    assert counts["skipped"] == 1
    mock.assert_not_called()
    ts = db.execute("SELECT feishu_sent FROM events WHERE id=?", (eid,)).fetchone()[0]
    assert ts is None
    captured = capsys.readouterr()
    assert "[dry-run]" in captured.out


def test_project_filter_only_processes_matching_project(db):
    _make_event(db, project="install", task_id="C1")
    _make_event(db, project="audit", task_id="A1")
    mock = _sent_mock()
    with patch(_PATCH_TARGET, mock):
        counts = announcer.process_once(conn=db, project_filter="install")
    assert counts["pending"] == 1
    mock.assert_called_once()
    # audit event still has feishu_sent=NULL
    ts = db.execute(
        "SELECT feishu_sent FROM events WHERE project='audit'"
    ).fetchone()[0]
    assert ts is None


def test_types_override_only_processes_configured_types(db):
    _make_event(db, type="task.completed", task_id="C1")
    _make_event(db, type="chain.closeout", task_id="CL1")
    mock = _sent_mock()
    with patch(_PATCH_TARGET, mock):
        counts = announcer.process_once(
            conn=db, event_types=("chain.closeout",)
        )
    assert counts["pending"] == 1
    mock.assert_called_once()


def test_user_decision_needed_sets_ask_user_and_required_gate(db):
    eid = _make_event(db, disposition="USER_DECISION_NEEDED")
    row = db.execute(
        "SELECT payload_json FROM events WHERE id=?", (eid,)
    ).fetchone()
    event = Event(id=eid, ts="2026-01-01", type="task.completed",
                  project="install", payload_json=row[0])
    envelope = announcer.build_envelope(event)
    assert "ask_user" in envelope
    assert "required" in envelope


def test_auto_advance_sets_proceed_and_none_gate(db):
    eid = _make_event(db, disposition="AUTO_ADVANCE")
    row = db.execute(
        "SELECT payload_json FROM events WHERE id=?", (eid,)
    ).fetchone()
    event = Event(id=eid, ts="2026-01-01", type="task.completed",
                  project="install", payload_json=row[0])
    envelope = announcer.build_envelope(event)
    assert "proceed" in envelope


def test_unknown_event_type_in_allow_list_graceful_degradation(db):
    conn = db
    conn.execute(
        "INSERT INTO events (ts, type, project, payload_json) VALUES "
        "(datetime('now'), 'weird.event', 'install', ?)",
        (json.dumps({"task_id": "X", "source": "a", "target": "b"}),),
    )
    conn.commit()
    mock = _sent_mock()
    with patch(_PATCH_TARGET, mock):
        counts = announcer.process_once(conn=db, event_types=("weird.event",))
    # build_envelope will fail (unknown event type not in _feishu VALID sets)
    # but loop must not crash — event lands in failed count
    assert counts["pending"] == 1


def test_no_pending_events_returns_zero_counts(db):
    counts = announcer.process_once(conn=db)
    assert counts == {"pending": 0, "sent": 0, "failed": 0, "skipped": 0, "retrying": 0}


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

def test_schema_migration_adds_feishu_sent_column_to_old_db(tmp_path):
    db_path = tmp_path / "state.db"
    # Simulate pre-C11 DB: events without feishu_sent column.
    conn0 = sqlite3.connect(str(db_path))
    conn0.execute(
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            type TEXT NOT NULL,
            project TEXT,
            payload_json TEXT NOT NULL
        )"""
    )
    conn0.execute(
        "INSERT INTO events (ts, type, project, payload_json) VALUES "
        "('2026-01-01', 'task.completed', 'install', '{\"task_id\":\"X\"}')"
    )
    conn0.commit()
    conn0.close()

    conn = open_db(db_path=db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert "feishu_sent" in cols
    row = conn.execute(
        "SELECT type, feishu_sent FROM events WHERE type='task.completed'"
    ).fetchone()
    assert row[0] == "task.completed"
    assert row[1] is None  # pre-existing rows survive with NULL
    conn.close()


def test_schema_migration_is_noop_on_already_migrated_db(tmp_path):
    db_path = tmp_path / "state.db"
    conn1 = open_db(db_path=db_path)
    conn1.close()
    conn2 = open_db(db_path=db_path)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(events)").fetchall()}
    assert "feishu_sent" in cols
    conn2.close()


# ---------------------------------------------------------------------------
# list_unsent_feishu_events / mark_feishu_sent helpers
# ---------------------------------------------------------------------------

def test_list_unsent_returns_only_null_feishu_sent(db):
    _make_event(db, task_id="C1")
    _make_event(db, task_id="C2", feishu_sent="2026-04-21T00:00:00")
    _make_event(db, task_id="C3")
    events = list_unsent_feishu_events(db)
    assert len(events) == 2
    ids = {e.payload_json for e in events}
    assert all("C2" not in p for p in ids)


def test_mark_feishu_sent_sets_timestamp(db):
    eid = _make_event(db)
    mark_feishu_sent(db, eid, "2026-04-21T12:00:00")
    ts = db.execute("SELECT feishu_sent FROM events WHERE id=?", (eid,)).fetchone()[0]
    assert ts == "2026-04-21T12:00:00"


def test_list_unsent_ordered_by_ts_ascending(db):
    for i in range(3):
        db.execute(
            "INSERT INTO events (ts, type, project, payload_json) VALUES (?, ?, 'install', ?)",
            (f"2026-04-2{i}", "task.completed", json.dumps({"task_id": f"T{i}"})),
        )
    db.commit()
    events = list_unsent_feishu_events(db)
    tss = [e.ts for e in events]
    assert tss == sorted(tss)


def test_list_unsent_project_filter(db):
    _make_event(db, project="install", task_id="C1")
    _make_event(db, project="audit", task_id="A1")
    events = list_unsent_feishu_events(db, project="install")
    assert len(events) == 1
    assert json.loads(events[0].payload_json)["task_id"] == "C1"


# ---------------------------------------------------------------------------
# CLI subprocess — end-to-end
# ---------------------------------------------------------------------------

def _base_env(db_path: Path) -> dict:
    import os
    return {**os.environ, "CLAWSEAT_STATE_DB": str(db_path)}


def test_cli_once_no_pending_exits_cleanly(tmp_path):
    db_path = tmp_path / "state.db"
    open_db(db_path=db_path).close()
    result = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / "core" / "scripts" / "feishu_announcer.py"),
         "--once"],
        capture_output=True, text=True, env=_base_env(db_path), timeout=30,
    )
    assert result.returncode == 0
    assert "no pending" in result.stdout.lower()


def test_cli_dry_run_prints_envelopes_no_db_write(tmp_path):
    db_path = tmp_path / "state.db"
    conn = open_db(db_path=db_path)
    _make_event(conn, task_id="C11")
    conn.close()

    result = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / "core" / "scripts" / "feishu_announcer.py"),
         "--dry-run", "--project", "install"],
        capture_output=True, text=True, env=_base_env(db_path), timeout=30,
    )
    assert result.returncode == 0
    assert "[dry-run]" in result.stdout

    conn2 = sqlite3.connect(str(db_path))
    ts = conn2.execute("SELECT feishu_sent FROM events LIMIT 1").fetchone()[0]
    conn2.close()
    assert ts is None


# ---------------------------------------------------------------------------
# build_parser — T7
# ---------------------------------------------------------------------------

def test_build_parser_announcer_defaults():
    p = announcer.build_parser()
    args = p.parse_args([])
    assert args.interval == 60.0
    assert not args.watch
    assert not getattr(args, "dry_run", False)
    assert args.project is None
    assert args.types is None


def test_build_parser_announcer_once_and_watch_mutually_exclusive():
    p = announcer.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--once", "--watch"])


def test_build_parser_announcer_accepts_project_and_types():
    p = announcer.build_parser()
    args = p.parse_args(["--once", "--project", "install",
                          "--types", "task.completed,chain.closeout"])
    assert args.project == "install"
    assert args.types == "task.completed,chain.closeout"


# ---------------------------------------------------------------------------
# T5 — run_watch() daemon in events_watcher.py
# ---------------------------------------------------------------------------

def test_run_watch_stops_on_sigint(tmp_path):
    db_path = tmp_path / "state.db"
    tasks_root = tmp_path / "tasks"
    tasks_root.mkdir()
    import os
    env = {**os.environ, "CLAWSEAT_STATE_DB": str(db_path)}
    proc = subprocess.Popen(
        [sys.executable,
         str(REPO_ROOT / "core" / "scripts" / "events_watcher.py"),
         "--watch", "--interval", "2",
         "--tasks-root", str(tasks_root)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    # Give it time to complete first cycle.
    time.sleep(1.0)
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail("events_watcher --watch did not stop after SIGINT within 5s")
    assert proc.returncode == 0
    stdout = proc.stdout.read()
    assert "stopped" in stdout.lower()


def test_run_watch_cycle_counter_increments(tmp_path):
    db_path = tmp_path / "state.db"
    tasks_root = tmp_path / "tasks"
    tasks_root.mkdir()
    import os
    env = {**os.environ, "CLAWSEAT_STATE_DB": str(db_path)}
    proc = subprocess.Popen(
        [sys.executable,
         str(REPO_ROOT / "core" / "scripts" / "events_watcher.py"),
         "--watch", "--interval", "0.1",
         "--tasks-root", str(tasks_root)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    # Wait until we see at least 2 cycle lines or 5s passes.
    deadline = time.monotonic() + 5.0
    output_lines: list[str] = []
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        output_lines.append(line)
        cycle_lines = [l for l in output_lines if "cycle" in l.lower()]
        if len(cycle_lines) >= 2:
            break
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    remaining = proc.stdout.read()
    all_output = "".join(output_lines) + remaining
    cycles = [l for l in all_output.splitlines() if "cycle" in l.lower()]
    assert len(cycles) >= 2, f"Expected ≥2 cycle lines, got: {all_output!r}"


def test_run_watch_unit_two_cycles_then_stop(tmp_path):
    db_path = tmp_path / "state.db"
    conn = open_db(db_path=db_path)
    tasks_root = tmp_path / "tasks"
    tasks_root.mkdir()

    stop_obj = watcher._SigintExit()
    cycle_count = [0]
    original_process_once = watcher.process_once

    def counting_process_once(*args, **kwargs):
        result = original_process_once(*args, **kwargs)
        cycle_count[0] += 1
        if cycle_count[0] >= 2:
            stop_obj.stop = True
        return result

    with patch.object(watcher, "process_once", counting_process_once):
        with patch.object(watcher, "_SigintExit", return_value=stop_obj):
            watcher.run_watch(conn, tasks_root, interval=0.05,
                              project_filter=None, dry_run=False)

    assert cycle_count[0] >= 2
    conn.close()


# ---------------------------------------------------------------------------
# T6 — record_event_if_new empty fingerprint guard
# ---------------------------------------------------------------------------

def test_record_event_if_new_empty_fingerprint_raises():
    db_path = Path("/tmp/test_t6_empty_fp.db")
    conn = open_db(db_path=db_path)
    try:
        with pytest.raises(ValueError, match="fingerprint"):
            record_event_if_new(conn, "task.completed", "install", "")
    finally:
        conn.close()
        db_path.unlink(missing_ok=True)


def test_record_event_if_new_valid_fingerprint_inserts(db):
    inserted = record_event_if_new(
        db, "task.completed", "install", "abc123def456abcd",
        task_id="X", source="a", target="b",
    )
    assert inserted is True
    count = db.execute("SELECT COUNT(*) FROM events WHERE fingerprint='abc123def456abcd'").fetchone()[0]
    assert count == 1


def test_record_event_if_new_duplicate_fingerprint_returns_false(db):
    fp = "abc123def456abcd"
    record_event_if_new(db, "task.completed", "install", fp, task_id="X")
    second = record_event_if_new(db, "task.completed", "install", fp, task_id="X")
    assert second is False
    count = db.execute("SELECT COUNT(*) FROM events WHERE fingerprint=?", (fp,)).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# T7 — build_parser() in events_watcher.py
# ---------------------------------------------------------------------------

def test_watcher_build_parser_defaults():
    p = watcher.build_parser()
    args = p.parse_args([])
    assert args.interval == 30.0
    assert not args.watch
    assert not args.once
    assert not args.dry_run
    assert args.project is None
    assert args.tasks_root is None


def test_watcher_build_parser_once_and_watch_mutually_exclusive():
    p = watcher.build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["--once", "--watch"])


def test_watcher_build_parser_tasks_root_accepted():
    p = watcher.build_parser()
    args = p.parse_args(["--once", "--tasks-root", "/tmp/tasks"])
    assert args.tasks_root == "/tmp/tasks"


def test_watcher_build_parser_project_filter_accepted():
    p = watcher.build_parser()
    args = p.parse_args(["--once", "--project", "install"])
    assert args.project == "install"


def test_watcher_build_parser_interval_accepted():
    p = watcher.build_parser()
    args = p.parse_args(["--watch", "--interval", "120"])
    assert args.interval == 120.0
