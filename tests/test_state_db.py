"""Tests for core/lib/state.py — C8 state.db kernel.

All tests use tmp_path and explicit db_path= — never touch ~/.agents/state.db.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from core.lib.state import (
    Event,
    Project,
    Seat,
    Task,
    get_project,
    get_seat,
    get_task,
    list_projects,
    list_seats,
    mark_task_completed,
    open_db,
    open_tasks_for_seat,
    pick_least_busy_seat,
    record_event,
    record_task_dispatched,
    seed_from_filesystem,
    upsert_project,
    upsert_seat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db(tmp_path: Path):
    return open_db(db_path=tmp_path / "state.db")


def _project(name="myproject", **kw) -> Project:
    defaults = dict(
        feishu_group_id="oc_abc",
        feishu_bot_account="koder",
        repo_root="/repos/myproject",
        heartbeat_owner="planner",
        active_loop_owner="planner",
        bound_at="2026-01-01T00:00:00+00:00",
    )
    defaults.update(kw)
    return Project(name=name, **defaults)


def _seat(project="myproject", seat_id="builder-1", role="builder", **kw) -> Seat:
    defaults = dict(
        tool="claude",
        auth_mode="oauth",
        provider="",
        status="live",
        last_heartbeat="2026-01-01T00:00:00+00:00",
        session_name="install-builder-1-claude",
        workspace="/workspaces/myproject/builder-1",
    )
    defaults.update(kw)
    return Seat(project=project, seat_id=seat_id, role=role, **defaults)


def _task(
    task_id="T1",
    project="myproject",
    source="planner",
    target="builder-1",
    status="dispatched",
    opened_at="2026-01-01T00:00:00+00:00",
    **kw,
) -> Task:
    return Task(
        id=task_id,
        project=project,
        source=source,
        target=target,
        status=status,
        opened_at=opened_at,
        **kw,
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

def test_schema_creates_tables(tmp_path):
    conn = _db(tmp_path)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"projects", "seats", "tasks", "events"}.issubset(tables)


def test_schema_reopen_is_noop(tmp_path):
    db_path = tmp_path / "state.db"
    conn1 = open_db(db_path=db_path)
    upsert_project(conn1, _project())
    conn1.close()

    conn2 = open_db(db_path=db_path)
    proj = get_project(conn2, "myproject")
    assert proj is not None
    assert proj.name == "myproject"


# ---------------------------------------------------------------------------
# Project round-trip
# ---------------------------------------------------------------------------

def test_upsert_get_project_roundtrip(tmp_path):
    conn = _db(tmp_path)
    orig = _project()
    upsert_project(conn, orig)
    got = get_project(conn, "myproject")
    assert got == orig


def test_list_projects(tmp_path):
    conn = _db(tmp_path)
    upsert_project(conn, _project("alpha"))
    upsert_project(conn, _project("beta"))
    names = [p.name for p in list_projects(conn)]
    assert names == ["alpha", "beta"]


def test_upsert_project_updates_fields(tmp_path):
    conn = _db(tmp_path)
    upsert_project(conn, _project(feishu_group_id="old"))
    upsert_project(conn, _project(feishu_group_id="new"))
    assert get_project(conn, "myproject").feishu_group_id == "new"


def test_get_project_missing_returns_none(tmp_path):
    conn = _db(tmp_path)
    assert get_project(conn, "nope") is None


# ---------------------------------------------------------------------------
# Seat round-trip
# ---------------------------------------------------------------------------

def test_upsert_get_seat_roundtrip(tmp_path):
    conn = _db(tmp_path)
    orig = _seat()
    upsert_seat(conn, orig)
    got = get_seat(conn, "myproject", "builder-1")
    assert got == orig


def test_list_seats_no_filter(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1"))
    upsert_seat(conn, _seat(seat_id="builder-2"))
    upsert_seat(conn, _seat(seat_id="reviewer-1", role="reviewer"))
    assert len(list_seats(conn, "myproject")) == 3


def test_list_seats_filter_by_role(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder"))
    upsert_seat(conn, _seat(seat_id="reviewer-1", role="reviewer"))
    builders = list_seats(conn, "myproject", role="builder")
    assert len(builders) == 1
    assert builders[0].seat_id == "builder-1"


def test_list_seats_filter_by_status(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", status="live"))
    upsert_seat(conn, _seat(seat_id="builder-2", status="stopped"))
    live = list_seats(conn, "myproject", status="live")
    assert len(live) == 1
    assert live[0].seat_id == "builder-1"


def test_list_seats_filter_role_and_status(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder", status="live"))
    upsert_seat(conn, _seat(seat_id="builder-2", role="builder", status="stopped"))
    upsert_seat(conn, _seat(seat_id="reviewer-1", role="reviewer", status="live"))
    result = list_seats(conn, "myproject", role="builder", status="live")
    assert len(result) == 1
    assert result[0].seat_id == "builder-1"


def test_get_seat_missing_returns_none(tmp_path):
    conn = _db(tmp_path)
    assert get_seat(conn, "myproject", "nobody") is None


# ---------------------------------------------------------------------------
# pick_least_busy_seat
# ---------------------------------------------------------------------------

def test_pick_returns_none_when_no_live_seats(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", status="stopped"))
    assert pick_least_busy_seat(conn, "myproject", "builder") is None


def test_pick_returns_none_when_no_matching_role(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder", status="live"))
    assert pick_least_busy_seat(conn, "myproject", "reviewer") is None


def test_pick_single_live_seat(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder", status="live"))
    seat = pick_least_busy_seat(conn, "myproject", "builder")
    assert seat is not None
    assert seat.seat_id == "builder-1"


def test_pick_least_busy_by_inflight_count(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder", status="live"))
    upsert_seat(conn, _seat(seat_id="builder-2", role="builder", status="live"))

    # Give builder-1 two in-flight tasks, builder-2 zero
    record_task_dispatched(conn, _task("T1", target="builder-1", status="dispatched"))
    record_task_dispatched(conn, _task("T2", target="builder-1", status="in_progress"))

    seat = pick_least_busy_seat(conn, "myproject", "builder")
    assert seat.seat_id == "builder-2"


def test_pick_tie_broken_alphabetically(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder", status="live"))
    upsert_seat(conn, _seat(seat_id="builder-2", role="builder", status="live"))
    # No tasks — equal inflight=0, tie broken by seat_id asc
    seat = pick_least_busy_seat(conn, "myproject", "builder")
    assert seat.seat_id == "builder-1"


def test_pick_ignores_completed_tasks(tmp_path):
    conn = _db(tmp_path)
    upsert_seat(conn, _seat(seat_id="builder-1", role="builder", status="live"))
    upsert_seat(conn, _seat(seat_id="builder-2", role="builder", status="live"))

    # builder-1 has one completed task (not in-flight)
    record_task_dispatched(conn, _task("T1", target="builder-1", status="dispatched"))
    mark_task_completed(conn, "T1")
    # builder-2 has one in-flight task
    record_task_dispatched(conn, _task("T2", target="builder-2", status="dispatched"))

    # builder-1 should win (0 in-flight vs 1)
    seat = pick_least_busy_seat(conn, "myproject", "builder")
    assert seat.seat_id == "builder-1"


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------

def test_record_and_get_task(tmp_path):
    conn = _db(tmp_path)
    t = _task("TASK-X", title="Do something")
    record_task_dispatched(conn, t)
    got = get_task(conn, "TASK-X")
    assert got is not None
    assert got.id == "TASK-X"
    assert got.title == "Do something"
    assert got.status == "dispatched"


def test_record_task_idempotent(tmp_path):
    conn = _db(tmp_path)
    t = _task("TASK-X")
    record_task_dispatched(conn, t)
    record_task_dispatched(conn, t)  # second insert should be silently ignored
    count = conn.execute("SELECT COUNT(*) FROM tasks WHERE id='TASK-X'").fetchone()[0]
    assert count == 1


def test_mark_task_completed(tmp_path):
    conn = _db(tmp_path)
    record_task_dispatched(conn, _task("TASK-X"))
    mark_task_completed(conn, "TASK-X", disposition="AUTO_ADVANCE")
    t = get_task(conn, "TASK-X")
    assert t.status == "completed"
    assert t.disposition == "AUTO_ADVANCE"
    assert t.closed_at is not None


def test_mark_task_completed_explicit_closed_at(tmp_path):
    conn = _db(tmp_path)
    record_task_dispatched(conn, _task("TASK-X"))
    mark_task_completed(conn, "TASK-X", closed_at="2026-06-01T12:00:00+00:00")
    t = get_task(conn, "TASK-X")
    assert t.closed_at == "2026-06-01T12:00:00+00:00"


def test_open_tasks_for_seat(tmp_path):
    conn = _db(tmp_path)
    record_task_dispatched(conn, _task("T1", target="builder-1", status="dispatched"))
    record_task_dispatched(conn, _task("T2", target="builder-1", status="in_progress"))
    record_task_dispatched(conn, _task("T3", target="builder-1", status="dispatched"))
    record_task_dispatched(conn, _task("T4", target="builder-2", status="dispatched"))
    mark_task_completed(conn, "T3")

    open_tasks = open_tasks_for_seat(conn, "myproject", "builder-1")
    ids = {t.id for t in open_tasks}
    assert ids == {"T1", "T2"}


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_record_event_and_read_back(tmp_path):
    conn = _db(tmp_path)
    record_event(conn, "task.dispatched", "myproject", task_id="T1", target="builder-1")
    rows = conn.execute("SELECT * FROM events ORDER BY ts DESC").fetchall()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["task_id"] == "T1"
    assert payload["target"] == "builder-1"


def test_record_multiple_events_ordered_by_ts_desc(tmp_path):
    conn = _db(tmp_path)
    record_event(conn, "seat.online", "myproject", seat="builder-1")
    record_event(conn, "seat.offline", "myproject", seat="builder-2")
    record_event(conn, "task.completed", "myproject", task_id="T99")

    rows = conn.execute("SELECT type FROM events ORDER BY ts DESC LIMIT 3").fetchall()
    types = [r["type"] for r in rows]
    # Most recent first
    assert types[0] == "task.completed"


def test_record_event_no_project(tmp_path):
    conn = _db(tmp_path)
    record_event(conn, "chain.closeout", None, info="none")
    rows = conn.execute("SELECT * FROM events").fetchall()
    assert rows[0]["project"] is None


# ---------------------------------------------------------------------------
# seed_from_filesystem
# ---------------------------------------------------------------------------

def _write_binding(tasks_dir: Path, project_name: str, **extra):
    proj_dir = tasks_dir / project_name
    proj_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "project": project_name,
        "feishu_group_id": extra.get("feishu_group_id", "oc_test"),
        "feishu_bot_account": extra.get("feishu_bot_account", "koder"),
        "bound_at": "2026-01-01T00:00:00+00:00",
    }
    lines = "\n".join(f'{k} = "{v}"' if isinstance(v, str) else f"{k} = {v}"
                      for k, v in data.items())
    (proj_dir / "PROJECT_BINDING.toml").write_text(lines + "\n")


def _write_session(sessions_dir: Path, project: str, seat_id: str,
                   session_name: str = "", tool: str = "claude",
                   auth_mode: str = "oauth"):
    seat_dir = sessions_dir / project / seat_id
    seat_dir.mkdir(parents=True, exist_ok=True)
    content = (
        f'project = "{project}"\n'
        f'engineer_id = "{seat_id}"\n'
        f'tool = "{tool}"\n'
        f'auth_mode = "{auth_mode}"\n'
    )
    if session_name:
        content += f'session = "{session_name}"\n'
    (seat_dir / "session.toml").write_text(content)


def _write_handoff(tasks_dir: Path, project: str, task_id: str,
                   kind: str = "dispatch", source: str = "planner",
                   target: str = "builder-1"):
    handoff_dir = tasks_dir / project / "patrol" / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": task_id,
        "kind": kind,
        "source": source,
        "target": target,
        "delivered_at": "2026-01-01T00:00:00+00:00",
    }
    (handoff_dir / f"{task_id}.json").write_text(json.dumps(data))


def _make_fake_home(tmp_path: Path, projects: list[str], seats_per_project: int = 4) -> Path:
    """Build a minimal fake ~/.agents tree with 2 projects × n seats."""
    home = tmp_path / "home"
    tasks_dir = home / ".agents" / "tasks"
    sessions_dir = home / ".agents" / "sessions"

    for proj in projects:
        _write_binding(tasks_dir, proj)
        for i in range(1, seats_per_project + 1):
            seat_id = f"builder-{i}"
            _write_session(sessions_dir, proj, seat_id,
                           session_name=f"{proj}-{seat_id}-claude")
        _write_handoff(tasks_dir, proj, f"{proj.upper()}-T1")
        _write_handoff(tasks_dir, proj, f"{proj.upper()}-T2", kind="completion")

    return home


def test_seed_fresh_counts(tmp_path):
    home = _make_fake_home(tmp_path, ["alpha", "beta"], seats_per_project=4)
    conn = open_db(db_path=tmp_path / "state.db")
    counts = seed_from_filesystem(home=home, conn=conn)
    assert counts["projects"] == 2
    assert counts["seats"] == 8  # 2 × 4
    assert counts["tasks"] >= 2  # at minimum ALPHA-T1 and BETA-T1 (insert-or-ignore)


def test_seed_idempotent(tmp_path):
    home = _make_fake_home(tmp_path, ["alpha"], seats_per_project=2)
    conn = open_db(db_path=tmp_path / "state.db")
    seed_from_filesystem(home=home, conn=conn)
    seed_from_filesystem(home=home, conn=conn)  # second run

    projs = list_projects(conn)
    assert len(projs) == 1
    seats = list_seats(conn, "alpha")
    assert len(seats) == 2


def test_seed_reseed_updates_status_but_not_completed_disposition(tmp_path):
    """Re-seeding with status drift: seat status may change, but completed
    tasks keep their disposition."""
    home = _make_fake_home(tmp_path, ["alpha"], seats_per_project=1)
    db_path = tmp_path / "state.db"
    conn = open_db(db_path=db_path)
    seed_from_filesystem(home=home, conn=conn)

    # Manually mark seat as stopped and a task as completed with disposition
    conn.execute(
        "UPDATE seats SET status='stopped' WHERE seat_id='builder-1'"
    )
    conn.execute(
        "UPDATE tasks SET status='completed', disposition='AUTO_ADVANCE', "
        "closed_at='2026-03-01T00:00:00+00:00' WHERE id='ALPHA-T1'"
    )
    conn.commit()

    # Re-seed — seats get status updated; completed task disposition preserved
    seed_from_filesystem(home=home, conn=conn)

    # Completed task: disposition must NOT be overwritten by seed
    # (record_task_dispatched uses INSERT OR IGNORE)
    task = get_task(conn, "ALPHA-T1")
    assert task is not None
    assert task.disposition == "AUTO_ADVANCE"


def test_seed_malformed_binding_skips_project(tmp_path):
    home = _make_fake_home(tmp_path, ["good"], seats_per_project=2)
    # Write a broken binding for a second project
    bad_dir = home / ".agents" / "tasks" / "broken"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "PROJECT_BINDING.toml").write_text("!!! not valid toml !!!")

    db_path = tmp_path / "state.db"
    conn = open_db(db_path=db_path)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        counts = seed_from_filesystem(home=home, conn=conn)

    # "good" project seeded; "broken" skipped with a warning
    assert counts["projects"] == 1
    projs = list_projects(conn)
    assert len(projs) == 1
    assert projs[0].name == "good"
    warning_messages = [str(warning.message) for warning in w]
    assert any("broken" in m for m in warning_messages)


def test_seed_malformed_session_skips_seat(tmp_path):
    home = _make_fake_home(tmp_path, ["alpha"], seats_per_project=0)
    # Write one valid and one broken session.toml
    sessions_dir = home / ".agents" / "sessions"
    _write_session(sessions_dir, "alpha", "builder-1")
    bad_dir = sessions_dir / "alpha" / "builder-bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "session.toml").write_text("!!! broken !!!")

    conn = open_db(db_path=tmp_path / "state.db")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        counts = seed_from_filesystem(home=home, conn=conn)

    assert counts["seats"] == 1
    assert any("builder-bad" in str(warning.message) for warning in w)
