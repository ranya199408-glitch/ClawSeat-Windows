"""Tests for dispatch_task.py idempotency guard (#16).

Gate logic: before appending to TODO.md, check if the same task_id already
exists under a [pending] or [queued] header. If so → exit 2 + TASK_ALREADY_QUEUED.

Scope: per-target (each TODO.md is independent; same task_id to different
targets is not a duplicate).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"

sys.path.insert(0, str(_SCRIPTS))
from dispatch_task import _is_task_already_queued  # noqa: E402


# ── Unit tests for _is_task_already_queued ──────────────────────────────────


def test_pending_entry_detected(tmp_path):
    """task_id under [pending] header returns True."""
    todo = tmp_path / "TODO.md"
    todo.write_text(
        "# Queue: builder-1\n\n"
        "## [pending] my-task\n"
        "task_id: my-task\n"
        "title: some task\n",
        encoding="utf-8",
    )
    assert _is_task_already_queued(todo, "my-task") is True


def test_queued_entry_detected(tmp_path):
    """task_id under [queued] header also returns True."""
    todo = tmp_path / "TODO.md"
    todo.write_text(
        "# Queue: builder-1\n\n"
        "## [pending] earlier-task\n"
        "task_id: earlier-task\n\n"
        "---\n\n"
        "## [queued] my-task\n"
        "task_id: my-task\n",
        encoding="utf-8",
    )
    assert _is_task_already_queued(todo, "my-task") is True


def test_different_task_id_not_detected(tmp_path):
    """Different task_id in file returns False."""
    todo = tmp_path / "TODO.md"
    todo.write_text(
        "# Queue: builder-1\n\n"
        "## [pending] existing-task\n"
        "task_id: existing-task\n",
        encoding="utf-8",
    )
    assert _is_task_already_queued(todo, "new-task") is False


def test_completed_entry_not_detected(tmp_path):
    """task_id under [completed] section returns False (not guarded)."""
    todo = tmp_path / "TODO.md"
    todo.write_text(
        "# Queue: builder-1\n\n"
        "# Completed\n\n"
        "- [2026-01-01] my-task — done\n",
        encoding="utf-8",
    )
    assert _is_task_already_queued(todo, "my-task") is False


def test_empty_todo_returns_false(tmp_path):
    """Non-existent or empty TODO.md returns False (normal dispatch allowed)."""
    missing = tmp_path / "NOPE.md"
    assert _is_task_already_queued(missing, "any-task") is False

    empty = tmp_path / "TODO.md"
    empty.write_text("", encoding="utf-8")
    assert _is_task_already_queued(empty, "any-task") is False


def test_multiple_pending_one_match_detected(tmp_path):
    """Multiple pending entries — matching one is enough to return True."""
    todo = tmp_path / "TODO.md"
    todo.write_text(
        "# Queue: builder-1\n\n"
        "## [pending] alpha\n"
        "task_id: alpha\n\n"
        "---\n\n"
        "## [queued] beta\n"
        "task_id: beta\n\n"
        "---\n\n"
        "## [queued] gamma\n"
        "task_id: gamma\n",
        encoding="utf-8",
    )
    assert _is_task_already_queued(todo, "beta") is True
    assert _is_task_already_queued(todo, "delta") is False


# ── Integration: subprocess exit code 2 when guard fires ───────────────────


def _make_minimal_profile(tmp_path: Path, seat: str = "builder-1") -> tuple[Path, Path]:
    """Create a minimal harness profile + tasks directory for subprocess tests."""
    tasks = tmp_path / "tasks"
    (tasks / seat).mkdir(parents=True)
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir()
    ws = tmp_path / "workspaces"
    ws.mkdir()

    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "test"
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
seats = ["planner", "{seat}"]
heartbeat_seats = []
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_owner = "koder"

[seat_roles]
planner = "planner-dispatcher"
{seat} = "builder"

[dynamic_roster]
materialized_seats = ["planner", "{seat}"]
""",
        encoding="utf-8",
    )
    return profile, tasks / seat / "TODO.md"


def _dispatch(tmp_path: Path, task_id: str, target: str = "builder-1") -> subprocess.CompletedProcess:
    profile, _ = _make_minimal_profile(tmp_path, seat=target)
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "dispatch_task.py"),
            "--profile", str(profile),
            "--source", "planner",
            "--target", target,
            "--task-id", task_id,
            "--title", f"test task {task_id}",
            "--objective", "test objective",
            "--test-policy", "UPDATE",
            "--reply-to", "planner",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )


def test_idempotent_guard_exits_2_on_duplicate(tmp_path):
    """Second dispatch of same task_id to same target → exit 2 + TASK_ALREADY_QUEUED."""
    profile, todo = _make_minimal_profile(tmp_path)
    # Prime the TODO with a pending entry manually
    todo.write_text(
        "# Queue: builder-1\n\n"
        "## [pending] dup-task\n"
        "task_id: dup-task\n"
        "title: original\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable, str(_SCRIPTS / "dispatch_task.py"),
            "--profile", str(profile),
            "--source", "planner",
            "--target", "builder-1",
            "--task-id", "dup-task",
            "--title", "duplicate",
            "--objective", "test",
            "--test-policy", "UPDATE",
            "--reply-to", "planner",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )
    assert result.returncode == 2
    assert "TASK_ALREADY_QUEUED" in result.stderr
    assert "dup-task" in result.stderr
