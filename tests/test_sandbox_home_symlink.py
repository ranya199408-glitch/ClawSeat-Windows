"""Tests for _link_sandbox_tasks_to_real_home (per-project symlink) in bootstrap_harness.py.

Covers: fresh creation, idempotency, wrong-target skip, real-dir-with-data skip,
legacy per-seat symlink migration, and --link-tasks CLI flag behaviour.
"""
from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from bootstrap_harness import _link_sandbox_tasks_to_real_home  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_profile(tmp_path: Path, project: str = "myproj") -> MagicMock:
    real_tasks = tmp_path / "real_tasks"
    real_tasks.mkdir(parents=True, exist_ok=True)
    profile = MagicMock()
    profile.project_name = project
    profile.tasks_root = real_tasks
    return profile


def _make_session(agents_home: Path, project: str, seat: str, sandbox_home: Path) -> Path:
    """Write a minimal session.toml so the linker can find sandbox_home."""
    session_dir = agents_home / "sessions" / project / seat
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / "session.toml"
    # runtime_dir is parent of sandbox_home (sandbox_home = runtime_dir/home)
    runtime_dir = sandbox_home.parent
    session_path.write_text(
        f'project = "{project}"\nengineer_id = "{seat}"\nruntime_dir = "{runtime_dir}"\n',
        encoding="utf-8",
    )
    sandbox_home.mkdir(parents=True, exist_ok=True)
    return session_path


# ── T1: fresh creation ───────────────────────────────────────────────────────

def test_link_creates_per_project_symlink_fresh(tmp_path):
    """No prior link — creates sandbox_home/.agents/tasks/<project> → real tasks_root."""
    agents_home = tmp_path / "agents"
    sandbox_home = tmp_path / "runtime" / "home"
    profile = _make_profile(tmp_path)
    _make_session(agents_home, profile.project_name, "seat1", sandbox_home)

    _link_sandbox_tasks_to_real_home(profile, ["seat1"], _agents_home=agents_home)

    link = sandbox_home / ".agents" / "tasks" / profile.project_name
    assert link.is_symlink(), f"Expected symlink at {link}"
    assert link.resolve() == profile.tasks_root.resolve()


# ── T2: idempotent ──────────────────────────────────────────────────────────

def test_link_is_idempotent_when_symlink_already_correct(tmp_path):
    """Calling twice with correct symlink already present → no error, symlink unchanged."""
    agents_home = tmp_path / "agents"
    sandbox_home = tmp_path / "runtime" / "home"
    profile = _make_profile(tmp_path)
    _make_session(agents_home, profile.project_name, "seat1", sandbox_home)

    link = sandbox_home / ".agents" / "tasks" / profile.project_name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(profile.tasks_root.resolve())

    # Second call must not raise or change the symlink
    _link_sandbox_tasks_to_real_home(profile, ["seat1"], _agents_home=agents_home)

    assert link.is_symlink()
    assert link.resolve() == profile.tasks_root.resolve()


# ── T3: wrong target → warn, skip ────────────────────────────────────────────

def test_link_warns_and_skips_when_symlink_points_elsewhere(tmp_path, capsys):
    """Symlink pointing to a different target → stderr warning, symlink not changed."""
    agents_home = tmp_path / "agents"
    sandbox_home = tmp_path / "runtime" / "home"
    profile = _make_profile(tmp_path)
    _make_session(agents_home, profile.project_name, "seat1", sandbox_home)

    other_target = tmp_path / "other_target"
    other_target.mkdir()
    link = sandbox_home / ".agents" / "tasks" / profile.project_name
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(other_target)

    _link_sandbox_tasks_to_real_home(profile, ["seat1"], _agents_home=agents_home)

    captured = capsys.readouterr()
    assert "symlink to different target" in captured.err
    assert link.resolve() == other_target.resolve()


# ── T4: regular dir with data → warn, skip ───────────────────────────────────

def test_link_warns_and_skips_when_regular_dir_has_data(tmp_path, capsys):
    """Real directory with a file inside → stderr warning, dir left intact."""
    agents_home = tmp_path / "agents"
    sandbox_home = tmp_path / "runtime" / "home"
    profile = _make_profile(tmp_path)
    _make_session(agents_home, profile.project_name, "seat1", sandbox_home)

    link = sandbox_home / ".agents" / "tasks" / profile.project_name
    link.mkdir(parents=True, exist_ok=True)
    (link / "a.txt").write_text("data", encoding="utf-8")

    _link_sandbox_tasks_to_real_home(profile, ["seat1"], _agents_home=agents_home)

    captured = capsys.readouterr()
    assert "regular dir with data" in captured.err
    assert link.is_dir() and not link.is_symlink()
    assert (link / "a.txt").exists()


# ── T5: legacy per-seat symlinks → migrate ───────────────────────────────────

def test_link_migrates_from_legacy_per_seat_symlinks(tmp_path):
    """Parent dir has only per-seat symlinks → removed, replaced by per-project symlink."""
    agents_home = tmp_path / "agents"
    sandbox_home = tmp_path / "runtime" / "home"
    profile = _make_profile(tmp_path)
    _make_session(agents_home, profile.project_name, "seat1", sandbox_home)

    # Build legacy layout: parent is real dir, children are symlinks
    parent = sandbox_home / ".agents" / "tasks" / profile.project_name
    parent.mkdir(parents=True, exist_ok=True)
    real_seat1 = profile.tasks_root / "seat1"
    real_seat1.mkdir(parents=True, exist_ok=True)
    real_seat2 = profile.tasks_root / "seat2"
    real_seat2.mkdir(parents=True, exist_ok=True)
    (parent / "seat1").symlink_to(real_seat1)
    (parent / "seat2").symlink_to(real_seat2)

    _link_sandbox_tasks_to_real_home(profile, ["seat1"], _agents_home=agents_home)

    assert parent.is_symlink(), "parent should now be a per-project symlink"
    assert parent.resolve() == profile.tasks_root.resolve()
    assert not (parent / "seat1").is_symlink()


# ── T6: --link-tasks CLI skips bootstrap ─────────────────────────────────────

def test_cli_link_tasks_flag_skips_bootstrap(tmp_path):
    """--link-tasks exits 0 without invoking project bootstrap (agent_admin absent → no error)."""
    # Build a minimal profile that references a non-existent agent_admin.
    # Normal bootstrap would fail because it calls run_command([..., agent_admin, "project", "bootstrap"])
    # With --link-tasks the bootstrap is skipped entirely → exit 0.
    profile_toml = tmp_path / "profile.toml"
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    profile_toml.write_text(
        f"""\
version = 1
profile_name = "test"
description = "test"
template_name = "gstack-harness"
project_name = "test"
repo_root = "{tmp_path}"
tasks_root = "{tasks_dir}"
project_doc = "{tasks_dir}/PROJECT.md"
tasks_doc = "{tasks_dir}/TASKS.md"
status_doc = "{tasks_dir}/STATUS.md"
send_script = "/nonexistent/send.sh"
status_script = "{tasks_dir}/patrol/check-status.sh"
patrol_script = "{tasks_dir}/patrol/patrol-supervisor.sh"
agent_admin = "/nonexistent/agent_admin.py"
workspace_root = "{tmp_path}/workspaces/test"
handoff_dir = "{tasks_dir}/patrol/handoffs"
heartbeat_owner = "koder"
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_receipt = "{tmp_path}/workspaces/test/koder/HEARTBEAT_RECEIPT.toml"
seats = ["koder"]
heartbeat_seats = ["koder"]
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "bootstrap_harness.py"), "--profile", str(profile_toml), "--link-tasks"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"


# ── T7: --link-tasks requires --profile ──────────────────────────────────────

def test_cli_link_tasks_requires_profile():
    """Omitting --profile with --link-tasks → argparse error exit 2."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "bootstrap_harness.py"), "--link-tasks"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, f"Expected exit 2 (argparse), got {result.returncode}"
