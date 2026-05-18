"""C9 dispatcher role-routing + ledger sync tests.

All tests use CLAWSEAT_STATE_DB env var + tmp_path — never touch real
~/.agents/state.db.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_MIGRATION = _REPO / "core" / "migration"

sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_SCRIPTS))

from core.lib.state import (  # noqa: E402
    Seat,
    Task,
    get_task,
    list_seats,
    open_db,
    record_task_dispatched,
    upsert_seat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_test_db(tmp_path: Path):
    db_path = tmp_path / "state.db"
    return open_db(db_path=db_path), db_path


def _make_profile(tmp_path: Path, seats: list[str] = None) -> tuple[Path, Path]:
    """Minimal harness profile with the given seat list."""
    if seats is None:
        seats = ["builder-1", "builder-2", "planner"]
    tasks = tmp_path / "tasks"
    for s in seats:
        (tasks / s).mkdir(parents=True, exist_ok=True)
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir(exist_ok=True)
    ws = tmp_path / "workspaces"
    ws.mkdir(exist_ok=True)

    seats_toml = str(seats).replace("'", '"')
    seat_roles_lines = "\n".join(
        f'{s} = "{"builder" if "builder" in s else "planner-dispatcher" if "planner" in s else "specialist"}"'
        for s in seats
    )
    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "testproject"
repo_root = "{tmp_path}"
tasks_root = "{tasks}"
workspace_root = "{ws}"
handoff_dir = "{handoffs}"
project_doc = "{tasks}/PROJECT.md"
tasks_doc = "{tasks}/TASKS.md"
status_doc = "{tasks}/STATUS.md"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
heartbeat_receipt = "{ws}/koder/HEARTBEAT_RECEIPT.toml"
seats = {seats_toml}
heartbeat_seats = []
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_owner = "koder"
heartbeat_transport = "openclaw"

[seat_roles]
{seat_roles_lines}

[dynamic_roster]
materialized_seats = {seats_toml}
""",
        encoding="utf-8",
    )
    return profile, tasks


def _init_git_repo(repo_root: Path) -> str:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo_root), "init", "-q", "-b", "main"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True)
    (repo_root / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo_root), "update-ref", "refs/remotes/clawseat/main", head], check=True)
    return head


def _seed_seats(conn, project: str, seats: list[tuple[str, str, str]]) -> None:
    """Seed (seat_id, role, status) into DB."""
    for seat_id, role, status in seats:
        upsert_seat(conn, Seat(
            project=project,
            seat_id=seat_id,
            role=role,
            tool="claude",
            auth_mode="oauth",
            status=status,
        ))


def _dispatch_cmd(profile: Path, target: str | None = None, target_role: str | None = None,
                  task_id: str = "T-TEST-001", title: str = "test task",
                  env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_SCRIPTS / "dispatch_task.py"),
        "--profile", str(profile),
        "--source", "planner",
        "--task-id", task_id,
        "--title", title,
        "--objective", "test objective",
        "--test-policy", "UPDATE",
        "--reply-to", "planner",
        "--no-notify",
    ]
    if target:
        cmd += ["--target", target]
    if target_role:
        cmd += ["--target-role", target_role]
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, env=merged_env)


def _complete_cmd(profile: Path, source: str, task_id: str,
                  env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_SCRIPTS / "complete_handoff.py"),
        "--profile", str(profile),
        "--source", source,
        "--target", "planner",
        "--task-id", task_id,
        "--summary", "done",
        "--no-notify",
    ]
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, env=merged_env)


# ---------------------------------------------------------------------------
# Unit: _write_dispatch_to_ledger / _write_completion_to_ledger
# ---------------------------------------------------------------------------

def test_dispatch_writes_task_row(tmp_path):
    """dispatch_task._write_dispatch_to_ledger inserts a task row."""
    conn, db_path = _open_test_db(tmp_path)
    from dispatch_task import _write_dispatch_to_ledger
    with patch.dict(os.environ, {"CLAWSEAT_STATE_DB": str(db_path)}):
        _write_dispatch_to_ledger(
            task_id="U-001",
            project="testproject",
            source="planner",
            target="builder-1",
            role_hint="builder",
            title="unit test task",
            correlation_id="abc123",
        )
    task = get_task(conn, "U-001")
    assert task is not None
    assert task.status == "dispatched"
    assert task.role_hint == "builder"
    assert task.target == "builder-1"


def test_dispatch_writes_event(tmp_path):
    """dispatch_task._write_dispatch_to_ledger also records a task.dispatched event."""
    conn, db_path = _open_test_db(tmp_path)
    from dispatch_task import _write_dispatch_to_ledger
    with patch.dict(os.environ, {"CLAWSEAT_STATE_DB": str(db_path)}):
        _write_dispatch_to_ledger(
            task_id="U-002",
            project="testproject",
            source="planner",
            target="builder-2",
            role_hint=None,
            title="event test",
            correlation_id=None,
        )
    rows = conn.execute("SELECT type FROM events WHERE type='task.dispatched'").fetchall()
    assert len(rows) == 1


def test_completion_writes_task_completed(tmp_path):
    """complete_handoff._write_completion_to_ledger marks task completed."""
    conn, db_path = _open_test_db(tmp_path)
    record_task_dispatched(conn, Task(
        id="U-003", project="testproject", source="planner",
        target="builder-1", status="dispatched",
        opened_at="2026-01-01T00:00:00+00:00",
    ))
    from complete_handoff import _write_completion_to_ledger
    with patch.dict(os.environ, {"CLAWSEAT_STATE_DB": str(db_path)}):
        _write_completion_to_ledger(
            task_id="U-003",
            project="testproject",
            source="builder-1",
            disposition="AUTO_ADVANCE",
        )
    task = get_task(conn, "U-003")
    assert task.status == "completed"
    assert task.disposition == "AUTO_ADVANCE"


def test_planner_memory_completion_writes_chain_closeout_event(tmp_path):
    conn, db_path = _open_test_db(tmp_path)
    record_task_dispatched(conn, Task(
        id="U-005", project="testproject", source="planner",
        target="memory", status="dispatched",
        opened_at="2026-01-01T00:00:00+00:00",
    ))
    from complete_handoff import _write_completion_to_ledger

    with patch.dict(os.environ, {"CLAWSEAT_STATE_DB": str(db_path)}):
        _write_completion_to_ledger(
            task_id="U-005",
            project="testproject",
            source="planner",
            target="memory",
            disposition="",
            event_type="chain.closeout",
            feishu_already_sent=True,
            human_summary="done",
        )

    row = conn.execute("SELECT type, payload_json FROM events WHERE type='chain.closeout'").fetchone()
    assert row is not None
    payload = json.loads(row[1])
    assert payload["target"] == "memory"
    assert payload["human_summary"] == "done"
    assert payload["feishu_already_sent"] is True
    task = get_task(conn, "U-005")
    assert task.closed_at is not None


def test_completion_writes_event(tmp_path):
    """complete_handoff._write_completion_to_ledger records task.completed event."""
    conn, db_path = _open_test_db(tmp_path)
    record_task_dispatched(conn, Task(
        id="U-004", project="testproject", source="planner",
        target="builder-1", status="dispatched",
        opened_at="2026-01-01T00:00:00+00:00",
    ))
    from complete_handoff import _write_completion_to_ledger
    with patch.dict(os.environ, {"CLAWSEAT_STATE_DB": str(db_path)}):
        _write_completion_to_ledger(
            task_id="U-004",
            project="testproject",
            source="builder-1",
            disposition="",
        )
    rows = conn.execute("SELECT type FROM events WHERE type='task.completed'").fetchall()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Unit: mutually exclusive --target / --target-role
# ---------------------------------------------------------------------------

def test_mutually_exclusive_flags_rejected(tmp_path):
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(profile, target="builder-1", target_role="builder")
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr.lower() or "error" in result.stderr.lower()


def test_neither_target_nor_target_role_rejected(tmp_path):
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(profile)  # no target, no target-role
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Integration: --target-role picks least-busy live seat
# ---------------------------------------------------------------------------

def test_target_role_picks_least_busy(tmp_path):
    """--target-role builder → routes to builder-2 (0 in-flight vs builder-1's 2)."""
    conn, db_path = _open_test_db(tmp_path)
    _seed_seats(conn, "testproject", [
        ("builder-1", "builder", "live"),
        ("builder-2", "builder", "live"),
    ])
    # Give builder-1 two in-flight tasks
    record_task_dispatched(conn, Task(
        id="BG-1", project="testproject", source="planner", target="builder-1",
        status="dispatched", opened_at="2026-01-01T00:00:00+00:00",
    ))
    record_task_dispatched(conn, Task(
        id="BG-2", project="testproject", source="planner", target="builder-1",
        status="in_progress", opened_at="2026-01-01T00:01:00+00:00",
    ))

    profile, _ = _make_profile(tmp_path, seats=["builder-1", "builder-2", "planner"])
    result = _dispatch_cmd(
        profile, target_role="builder", task_id="ROLE-001",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 0, result.stderr
    # Receipt should show target=builder-2
    handoffs = list((tmp_path / "handoffs").glob("ROLE-001*.json"))
    assert len(handoffs) == 1
    receipt = json.loads(handoffs[0].read_text())
    assert receipt["target"] == "builder-2"
    # Ledger should have the task row
    task = get_task(conn, "ROLE-001")
    assert task is not None
    assert task.target == "builder-2"
    assert task.role_hint == "builder"


def test_target_role_seat_needed_no_live_seats(tmp_path):
    """--target-role when no live seats → rc=3, seat_needed in stderr."""
    conn, db_path = _open_test_db(tmp_path)
    _seed_seats(conn, "testproject", [
        ("builder-1", "builder", "stopped"),
        ("builder-2", "builder", "stopped"),
    ])
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(
        profile, target_role="builder", task_id="ROLE-002",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 3
    assert "seat_needed" in result.stderr
    # No task row created
    assert get_task(conn, "ROLE-002") is None
    # No event recorded
    rows = conn.execute(
        "SELECT * FROM events WHERE payload_json LIKE '%ROLE-002%'"
    ).fetchall()
    assert len(rows) == 0


def test_target_role_seat_needed_wrong_role(tmp_path):
    """--target-role reviewer when only builder seats live → rc=3."""
    conn, db_path = _open_test_db(tmp_path)
    _seed_seats(conn, "testproject", [("builder-1", "builder", "live")])
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(
        profile, target_role="reviewer", task_id="ROLE-003",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 3
    assert "seat_needed" in result.stderr


def test_target_role_resolved_printed_to_stderr(tmp_path):
    """Stderr contains 'target-role resolved: builder -> builderX' when seat found."""
    conn, db_path = _open_test_db(tmp_path)
    _seed_seats(conn, "testproject", [("builder-1", "builder", "live")])
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(
        profile, target_role="builder", task_id="ROLE-004",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 0, result.stderr
    assert "target-role resolved: builder -> builder-1" in result.stderr


# ---------------------------------------------------------------------------
# Integration: legacy --target still works
# ---------------------------------------------------------------------------

def test_legacy_target_still_works(tmp_path):
    """--target builder-1 without state.db → rc=0, receipt written, role_hint=null."""
    profile, _ = _make_profile(tmp_path)
    # No DB seeded — defensive: dispatch should still succeed even if DB is absent
    result = _dispatch_cmd(
        profile, target="builder-1", task_id="LEGACY-001",
        env={"CLAWSEAT_STATE_DB": str(tmp_path / "nonexistent.db")},
    )
    assert result.returncode == 0, result.stderr
    handoffs = list((tmp_path / "handoffs").glob("LEGACY-001*.json"))
    assert len(handoffs) == 1
    receipt = json.loads(handoffs[0].read_text())
    assert receipt["target"] == "builder-1"


def test_legacy_target_ledger_role_hint_null(tmp_path):
    """When --target is used, ledger task row has role_hint=None."""
    conn, db_path = _open_test_db(tmp_path)
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_cmd(
        profile, target="builder-1", task_id="LEGACY-002",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 0, result.stderr
    task = get_task(conn, "LEGACY-002")
    assert task is not None
    assert task.role_hint is None


# ---------------------------------------------------------------------------
# Integration: ledger sync across full dispatch → complete cycle
# ---------------------------------------------------------------------------

def test_ledger_sync_dispatch_then_complete(tmp_path):
    """After dispatch + complete, ledger shows dispatched then completed."""
    conn, db_path = _open_test_db(tmp_path)
    db_env = {"CLAWSEAT_STATE_DB": str(db_path)}
    profile, _ = _make_profile(tmp_path)

    # Dispatch
    r1 = _dispatch_cmd(profile, target="builder-1", task_id="SYNC-001", env=db_env)
    assert r1.returncode == 0, r1.stderr
    task = get_task(conn, "SYNC-001")
    assert task is not None
    assert task.status == "dispatched"

    # Verify task.dispatched event
    rows = conn.execute(
        "SELECT type FROM events WHERE payload_json LIKE '%SYNC-001%'"
    ).fetchall()
    assert any(r["type"] == "task.dispatched" for r in rows)

    # Complete
    r2 = _complete_cmd(profile, source="builder-1", task_id="SYNC-001", env=db_env)
    assert r2.returncode == 0, r2.stderr
    task = get_task(conn, "SYNC-001")
    assert task.status == "completed"
    assert task.closed_at is not None

    # Verify task.completed event
    rows = conn.execute(
        "SELECT type FROM events WHERE payload_json LIKE '%SYNC-001%'"
    ).fetchall()
    types = {r["type"] for r in rows}
    assert "task.dispatched" in types
    assert "task.completed" in types


# ---------------------------------------------------------------------------
# Integration: defensive — DB missing/locked does not fail dispatch
# ---------------------------------------------------------------------------

def _make_unwritable_db_path(tmp_path: Path) -> str:
    """Return a state.db path that cannot be opened: parent is a regular file."""
    fake_parent = tmp_path / "not_a_dir.txt"
    fake_parent.write_text("blocking file", encoding="utf-8")
    return str(fake_parent / "state.db")


def test_defensive_db_missing_dispatch_still_succeeds(tmp_path):
    """If state.db path is unwritable, dispatch still succeeds (rc=0, receipt written)."""
    profile, _ = _make_profile(tmp_path)
    bad_db = _make_unwritable_db_path(tmp_path)
    result = _dispatch_cmd(
        profile, target="builder-1", task_id="DEF-001",
        env={"CLAWSEAT_STATE_DB": bad_db},
    )
    # Dispatch must still succeed regardless of DB failure
    assert result.returncode == 0, result.stderr
    # Receipt still written
    handoffs = list((tmp_path / "handoffs").glob("DEF-001*.json"))
    assert len(handoffs) == 1
    # Warning emitted to stderr
    assert "warn" in result.stderr.lower()


def test_defensive_db_missing_complete_still_succeeds(tmp_path):
    """If state.db write fails, complete_handoff still succeeds."""
    conn, db_path = _open_test_db(tmp_path)
    db_env = {"CLAWSEAT_STATE_DB": str(db_path)}
    profile, _ = _make_profile(tmp_path)

    # Dispatch first (to a real DB so the handoff receipt exists for complete)
    r1 = _dispatch_cmd(profile, target="builder-1", task_id="DEF-002", env=db_env)
    assert r1.returncode == 0, r1.stderr

    # Complete with an unwritable DB path
    bad2 = tmp_path / "bad2"
    bad2.mkdir()
    bad_db = _make_unwritable_db_path(bad2)
    r2 = _complete_cmd(
        profile, source="builder-1", task_id="DEF-002",
        env={"CLAWSEAT_STATE_DB": bad_db},
    )
    assert r2.returncode == 0, r2.stderr
    assert "warn" in r2.stderr.lower()


# ---------------------------------------------------------------------------
# Integration: drift guard — dynamic variants also write to ledger
# ---------------------------------------------------------------------------

def _dispatch_dynamic_cmd(profile: Path, target: str | None = None,
                           target_role: str | None = None, task_id: str = "DYN-001",
                           env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_MIGRATION / "dispatch_task_dynamic.py"),
        "--profile", str(profile),
        "--source", "planner",
        "--task-id", task_id,
        "--title", "dynamic test task",
        "--objective", "test objective",
        "--test-policy", "UPDATE",
        "--no-notify",
    ]
    if target:
        cmd += ["--target", target]
    if target_role:
        cmd += ["--target-role", target_role]
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, env=merged_env)


def _complete_dynamic_cmd(profile: Path, source: str, task_id: str,
                           env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_MIGRATION / "complete_handoff_dynamic.py"),
        "--profile", str(profile),
        "--source", source,
        "--target", "planner",
        "--task-id", task_id,
        "--summary", "done",
        "--no-notify",
    ]
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, env=merged_env)


def test_dynamic_dispatch_writes_to_ledger(tmp_path):
    """dispatch_task_dynamic.py also writes task row + event to state.db."""
    conn, db_path = _open_test_db(tmp_path)
    db_env = {"CLAWSEAT_STATE_DB": str(db_path)}
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_dynamic_cmd(profile, target="builder-1", task_id="DYN-001", env=db_env)
    assert result.returncode == 0, result.stderr
    task = get_task(conn, "DYN-001")
    assert task is not None
    assert task.status == "dispatched"
    rows = conn.execute("SELECT type FROM events WHERE payload_json LIKE '%DYN-001%'").fetchall()
    assert any(r["type"] == "task.dispatched" for r in rows)


def test_dynamic_dispatch_records_lineage_fields(tmp_path):
    """dispatch_task_dynamic.py writes production lineage fields into receipts."""
    expected = _init_git_repo(tmp_path)
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_dynamic_cmd(profile, target="builder-1", task_id="DYN-LINEAGE")
    assert result.returncode == 0, result.stderr
    receipt = json.loads((tmp_path / "handoffs" / "DYN-LINEAGE__planner__builder-1.json").read_text(encoding="utf-8"))
    assert receipt["expected_base_sha"] == expected
    assert receipt["builder_commit"] == expected
    assert receipt["memory_commit"] is None
    assert receipt["head_contains_commit"] is True
    assert receipt["lineage_status"] == "in-lineage"


def test_dynamic_complete_writes_to_ledger(tmp_path):
    """complete_handoff_dynamic.py also calls mark_task_completed + records event."""
    conn, db_path = _open_test_db(tmp_path)
    db_env = {"CLAWSEAT_STATE_DB": str(db_path)}
    profile, _ = _make_profile(tmp_path)

    r1 = _dispatch_dynamic_cmd(profile, target="builder-1", task_id="DYN-002", env=db_env)
    assert r1.returncode == 0, r1.stderr

    r2 = _complete_dynamic_cmd(profile, source="builder-1", task_id="DYN-002", env=db_env)
    assert r2.returncode == 0, r2.stderr

    task = get_task(conn, "DYN-002")
    assert task.status == "completed"
    rows = conn.execute("SELECT type FROM events WHERE payload_json LIKE '%DYN-002%'").fetchall()
    types = {r["type"] for r in rows}
    assert "task.dispatched" in types
    assert "task.completed" in types


def test_dynamic_target_role_picks_least_busy(tmp_path):
    """dispatch_task_dynamic.py --target-role resolves via state.db."""
    conn, db_path = _open_test_db(tmp_path)
    _seed_seats(conn, "testproject", [
        ("builder-1", "builder", "live"),
        ("builder-2", "builder", "live"),
    ])
    record_task_dispatched(conn, Task(
        id="DG-1", project="testproject", source="planner", target="builder-1",
        status="dispatched", opened_at="2026-01-01T00:00:00+00:00",
    ))
    profile, _ = _make_profile(tmp_path, seats=["builder-1", "builder-2", "planner"])
    result = _dispatch_dynamic_cmd(
        profile, target_role="builder", task_id="DYN-003",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 0, result.stderr
    task = get_task(conn, "DYN-003")
    assert task is not None
    assert task.target == "builder-2"


def test_dynamic_target_role_seat_needed(tmp_path):
    """dispatch_task_dynamic.py --target-role with no live seats → rc=3."""
    conn, db_path = _open_test_db(tmp_path)
    _seed_seats(conn, "testproject", [("builder-1", "builder", "stopped")])
    profile, _ = _make_profile(tmp_path)
    result = _dispatch_dynamic_cmd(
        profile, target_role="builder", task_id="DYN-004",
        env={"CLAWSEAT_STATE_DB": str(db_path)},
    )
    assert result.returncode == 3
    assert "seat_needed" in result.stderr
    assert get_task(conn, "DYN-004") is None
