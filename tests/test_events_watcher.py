"""Tests for core/scripts/events_watcher.py — C10 passive watcher.

All tests use tmp_path fixtures so ~/.agents/state.db is never touched.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.lib.state import open_db, record_event
from core.scripts import events_watcher as watcher


REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_handoff(
    tasks_root: Path,
    project: str,
    filename: str,
    payload: dict,
) -> Path:
    handoff_dir = tasks_root / project / "patrol" / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    path = handoff_dir / filename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _dispatch(task_id: str, source: str = "planner", target: str = "builder-1") -> dict:
    return {
        "kind": "dispatch",
        "task_id": task_id,
        "source": source,
        "target": target,
        "title": f"{task_id} title",
        "correlation_id": "deadbeef",
        "assigned_at": "2026-04-21T00:00:00+00:00",
    }


def _completion(task_id: str, source: str = "builder-1", target: str = "planner") -> dict:
    return {
        "kind": "completion",
        "task_id": task_id,
        "source": source,
        "target": target,
        "frontstage_disposition": "USER_DECISION_NEEDED",
        "delivered_at": "2026-04-21T01:00:00+00:00",
        "correlation_id": "cafebabe",
    }


def _learning(task_id: str = "PATROL-1") -> dict:
    return {
        "kind": "learning",
        "task_id": task_id,
        "source": "ancestor",
        "target": "planner",
        "message": "patrol notes go here",
    }


def _notice(task_id: str = "NOTICE-1") -> dict:
    return {
        "kind": "notice",
        "task_id": task_id,
        "source": "patrol",
        "target": "planner",
        "message": "heads up",
    }


@pytest.fixture()
def fresh_db(tmp_path: Path) -> sqlite3.Connection:
    conn = open_db(db_path=tmp_path / "state.db")
    yield conn
    conn.close()


@pytest.fixture()
def tasks_root(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Event derivation
# ---------------------------------------------------------------------------

def test_derive_event_dispatch():
    event_type, payload, fp = watcher.derive_event(
        _dispatch("T1"), "install"
    )
    assert event_type == "task.dispatched"
    assert payload == {
        "task_id": "T1", "source": "planner",
        "target": "builder-1", "title": "T1 title",
    }
    assert len(fp) == 16


def test_derive_event_completion():
    event_type, payload, _ = watcher.derive_event(
        _completion("T1"), "install"
    )
    assert event_type == "task.completed"
    assert payload["disposition"] == "USER_DECISION_NEEDED"


def test_derive_event_learning():
    event_type, payload, _ = watcher.derive_event(_learning(), "install")
    assert event_type == "patrol.learning"
    assert payload["message"] == "patrol notes go here"


def test_derive_event_notice_reminder_unblock_all_map_to_seat_notified():
    for kind in ("notice", "reminder", "unblock"):
        handoff = dict(_notice(), kind=kind)
        et, payload, _ = watcher.derive_event(handoff, "install")
        assert et == "seat.notified"
        assert payload["kind"] == kind


def test_derive_event_unknown_preserves_raw():
    et, payload, _ = watcher.derive_event(
        {"kind": "mystery", "task_id": "X", "foo": "bar"}, "install"
    )
    assert et == "handoff.unknown"
    assert payload["raw"]["foo"] == "bar"


def test_derive_event_fingerprint_is_deterministic():
    h = _dispatch("T1")
    _, _, fp1 = watcher.derive_event(h, "install")
    _, _, fp2 = watcher.derive_event(h, "install")
    assert fp1 == fp2
    _, _, fp_other_project = watcher.derive_event(h, "audit")
    assert fp1 != fp_other_project


# ---------------------------------------------------------------------------
# process_once
# ---------------------------------------------------------------------------

def test_fresh_run_writes_all(fresh_db, tasks_root):
    for i in range(3):
        _write_handoff(tasks_root, "install", f"T{i}__planner__builder-1.json",
                       _dispatch(f"T{i}"))
    for i in range(2):
        _write_handoff(tasks_root, "install", f"T{i}__builder-1__planner.json",
                       _completion(f"T{i}"))
    counts = watcher.process_once(fresh_db, tasks_root)
    assert counts == {
        "processed": 5, "written": 5, "skipped": 0,
        "malformed": 0, "unknown": 0,
    }
    rows = fresh_db.execute(
        "SELECT type, COUNT(*) FROM events GROUP BY type ORDER BY type"
    ).fetchall()
    by_type = {r[0]: r[1] for r in rows}
    assert by_type == {"task.completed": 2, "task.dispatched": 3}


def test_idempotent_rerun(fresh_db, tasks_root):
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    first = watcher.process_once(fresh_db, tasks_root)
    second = watcher.process_once(fresh_db, tasks_root)
    assert first["written"] == 1 and first["skipped"] == 0
    assert second["written"] == 0 and second["skipped"] == 1
    count = fresh_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 1


def test_new_handoff_mid_watch_picked_up_next_cycle(fresh_db, tasks_root):
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    c1 = watcher.process_once(fresh_db, tasks_root)
    assert c1["written"] == 1
    _write_handoff(tasks_root, "install", "T2__planner__builder-1.json",
                   _dispatch("T2"))
    c2 = watcher.process_once(fresh_db, tasks_root)
    assert c2 == {"processed": 2, "written": 1, "skipped": 1,
                  "malformed": 0, "unknown": 0}


def test_legacy_events_coexist(fresh_db, tasks_root):
    # Pre-existing event from direct record_event() — no fingerprint.
    record_event(fresh_db, "task.dispatched", "install",
                 task_id="LEGACY", source="planner", target="builder-1")
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    counts = watcher.process_once(fresh_db, tasks_root)
    assert counts["written"] == 1
    total = fresh_db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total == 2
    fp_nulls = fresh_db.execute(
        "SELECT COUNT(*) FROM events WHERE fingerprint IS NULL"
    ).fetchone()[0]
    assert fp_nulls == 1


def test_dry_run_does_not_write(fresh_db, tasks_root, capsys):
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    counts = watcher.process_once(fresh_db, tasks_root, dry_run=True)
    assert counts["written"] == 0 and counts["processed"] == 1
    captured = capsys.readouterr()
    assert "[dry-run]" in captured.out
    assert fresh_db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_project_filter(fresh_db, tasks_root):
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    _write_handoff(tasks_root, "audit", "A1__planner__builder-1.json",
                   _dispatch("A1"))
    counts = watcher.process_once(fresh_db, tasks_root, project_filter="install")
    assert counts["processed"] == 1 and counts["written"] == 1
    rows = fresh_db.execute("SELECT project FROM events").fetchall()
    assert {r[0] for r in rows} == {"install"}


def test_malformed_json_is_skipped(fresh_db, tasks_root, caplog):
    handoff_dir = tasks_root / "install" / "patrol" / "handoffs"
    handoff_dir.mkdir(parents=True)
    (handoff_dir / "bad.json").write_text("{not json", encoding="utf-8")
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    with caplog.at_level("WARNING"):
        counts = watcher.process_once(fresh_db, tasks_root)
    assert counts["processed"] == 2
    assert counts["written"] == 1
    assert counts["malformed"] == 1
    assert any("malformed" in rec.message for rec in caplog.records)


def test_unknown_kind_logs_warning_and_records(fresh_db, tasks_root, caplog):
    _write_handoff(tasks_root, "install", "X__a__b.json",
                   {"kind": "mystery", "task_id": "X",
                    "source": "a", "target": "b"})
    with caplog.at_level("WARNING"):
        counts = watcher.process_once(fresh_db, tasks_root)
    assert counts["written"] == 1 and counts["unknown"] == 1
    assert any("unknown kind" in rec.message for rec in caplog.records)
    row = fresh_db.execute(
        "SELECT type, payload_json FROM events"
    ).fetchone()
    assert row[0] == "handoff.unknown"
    assert "mystery" in row[1]


# ---------------------------------------------------------------------------
# Schema migration
# ---------------------------------------------------------------------------

def test_schema_migration_adds_fingerprint_column_to_old_db(tmp_path):
    db_path = tmp_path / "state.db"
    # Build an old-schema DB manually: events table without fingerprint.
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
        "('2026-01-01', 'legacy.event', 'install', '{}')"
    )
    conn0.commit()
    conn0.close()

    # open_db should ALTER ADD COLUMN without error.
    conn = open_db(db_path=db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    assert "fingerprint" in cols
    # Pre-existing row survives with NULL fingerprint.
    row = conn.execute(
        "SELECT type, fingerprint FROM events WHERE type='legacy.event'"
    ).fetchone()
    assert row[0] == "legacy.event"
    assert row[1] is None
    conn.close()


def test_opening_fresh_db_twice_is_noop(tmp_path):
    db_path = tmp_path / "state.db"
    conn1 = open_db(db_path=db_path)
    conn1.close()
    # Second open must not raise despite ALTER TABLE having no-op target.
    conn2 = open_db(db_path=db_path)
    conn2.close()


# ---------------------------------------------------------------------------
# CLI end-to-end (via subprocess)
# ---------------------------------------------------------------------------

def test_cli_once_end_to_end(tmp_path, monkeypatch):
    db_path = tmp_path / "state.db"
    tasks_root = tmp_path / "tasks"
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    env = dict(
        **{k: v for k, v in __import__("os").environ.items()},
        CLAWSEAT_STATE_DB=str(db_path),
    )
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core" / "scripts" / "events_watcher.py"),
         "--once", "--tasks-root", str(tasks_root)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "processed=1" in result.stdout
    assert "written=1" in result.stdout

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT type, fingerprint FROM events"
    ).fetchone()
    conn.close()
    assert row[0] == "task.dispatched"
    assert row[1] is not None and len(row[1]) == 16


def test_cli_project_filter(tmp_path):
    db_path = tmp_path / "state.db"
    tasks_root = tmp_path / "tasks"
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    _write_handoff(tasks_root, "audit", "A1__planner__builder-1.json",
                   _dispatch("A1"))
    env = dict(
        **{k: v for k, v in __import__("os").environ.items()},
        CLAWSEAT_STATE_DB=str(db_path),
    )
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core" / "scripts" / "events_watcher.py"),
         "--once", "--tasks-root", str(tasks_root), "--project", "audit"],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(db_path))
    projects = {r[0] for r in conn.execute("SELECT project FROM events").fetchall()}
    conn.close()
    assert projects == {"audit"}


def test_cli_dry_run_writes_nothing(tmp_path):
    db_path = tmp_path / "state.db"
    tasks_root = tmp_path / "tasks"
    _write_handoff(tasks_root, "install", "T1__planner__builder-1.json",
                   _dispatch("T1"))
    env = dict(
        **{k: v for k, v in __import__("os").environ.items()},
        CLAWSEAT_STATE_DB=str(db_path),
    )
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core" / "scripts" / "events_watcher.py"),
         "--once", "--dry-run", "--tasks-root", str(tasks_root)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "[dry-run]" in result.stdout
    # state.db may exist (open_db creates it), but events table must be empty.
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    assert count == 0
