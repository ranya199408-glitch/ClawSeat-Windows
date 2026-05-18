from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core" / "skills" / "gstack-harness" / "scripts" / "complete_handoff.py"


def _write_profile(
    path: Path,
    *,
    handoff_dir: str,
    workspace_root: Path,
) -> Path:
    tasks_root = path.parent / "tasks"
    for seat in ("planner", "memory", "koder"):
        (tasks_root / seat).mkdir(parents=True, exist_ok=True)
        (workspace_root / seat).mkdir(parents=True, exist_ok=True)
    (tasks_root / "STATUS.md").write_text("# status\n", encoding="utf-8")
    (tasks_root / "PROJECT.md").write_text("# project\n", encoding="utf-8")
    (tasks_root / "TASKS.md").write_text("# tasks\n", encoding="utf-8")
    path.write_text(
        "\n".join(
            [
                'version = 1',
                'profile_name = "test-profile"',
                'template_name = "gstack-harness"',
                'project_name = "test"',
                f'repo_root = "{REPO}"',
                f'tasks_root = "{tasks_root}"',
                f'workspace_root = "{workspace_root}"',
                f'handoff_dir = "{handoff_dir}"',
                f'project_doc = "{tasks_root / "PROJECT.md"}"',
                f'tasks_doc = "{tasks_root / "TASKS.md"}"',
                f'status_doc = "{tasks_root / "STATUS.md"}"',
                'send_script = "/bin/echo"',
                'status_script = "/bin/echo"',
                'patrol_script = "/bin/echo"',
                'agent_admin = "/bin/echo"',
                f'heartbeat_receipt = "{workspace_root / "koder" / "HEARTBEAT_RECEIPT.toml"}"',
                'seats = ["planner", "memory"]',
                'heartbeat_seats = []',
                'active_loop_owner = "planner"',
                'default_notify_target = "planner"',
                'heartbeat_owner = "koder"',
                'heartbeat_transport = "tmux"',
                '',
                '[seat_roles]',
                'planner = "planner-dispatcher"',
                'memory = "memory"',
                '',
                '[dynamic_roster]',
                'enabled = false',
            ]
        ),
        encoding="utf-8",
    )
    return path


def _seed_dispatch(handoff_dir: Path, task_id: str) -> Path:
    handoff_dir.mkdir(parents=True, exist_ok=True)
    path = handoff_dir / f"{task_id}__memory__planner.json"
    path.write_text(
        json.dumps(
            {
                "kind": "dispatch",
                "task_id": task_id,
                "source": "memory",
                "target": "planner",
                "reply_to": "memory",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _run_complete(profile: Path, task_id: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target",
            "memory",
            "--task-id",
            task_id,
            "--summary",
            "done",
            "--status",
            "completed",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT.parent),
        env=env,
    )


def test_helper_with_tilde_path_expands_and_renames(tmp_path: Path, monkeypatch) -> None:
    real_home = tmp_path / "real-home"
    profile_path = real_home / "profile.toml"
    handoff_dir = real_home / "test-handoff-tilde"
    workspace_root = tmp_path / "workspaces"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    profile = _write_profile(profile_path, handoff_dir="~/test-handoff-tilde", workspace_root=workspace_root)
    _seed_dispatch(handoff_dir, "DJ-T1")

    result = _run_complete(profile, "DJ-T1", os.environ.copy())

    assert result.returncode == 0, result.stderr
    assert (handoff_dir / "DJ-T1__memory__planner.json.consumed").exists()
    assert not (handoff_dir / "DJ-T1__memory__planner.json").exists()


def test_helper_with_dollar_home_path_expands(tmp_path: Path, monkeypatch) -> None:
    real_home = tmp_path / "real-home"
    profile_path = real_home / "profile.toml"
    handoff_dir = real_home / "test-handoff-dollar"
    workspace_root = tmp_path / "workspaces"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    profile = _write_profile(profile_path, handoff_dir="$HOME/test-handoff-dollar", workspace_root=workspace_root)
    _seed_dispatch(handoff_dir, "DJ-T2")

    result = _run_complete(profile, "DJ-T2", os.environ.copy())

    assert result.returncode == 0, result.stderr
    assert (handoff_dir / "DJ-T2__memory__planner.json.consumed").exists()


def test_helper_with_absolute_path_unchanged(tmp_path: Path, monkeypatch) -> None:
    real_home = tmp_path / "real-home"
    profile_path = real_home / "profile.toml"
    handoff_dir = tmp_path / "handoffs-abs"
    workspace_root = tmp_path / "workspaces"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    profile = _write_profile(profile_path, handoff_dir=str(handoff_dir), workspace_root=workspace_root)
    _seed_dispatch(handoff_dir, "DJ-T3")

    result = _run_complete(profile, "DJ-T3", os.environ.copy())

    assert result.returncode == 0, result.stderr
    assert (handoff_dir / "DJ-T3__memory__planner.json.consumed").exists()


def test_helper_handoffs_dir_missing_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    real_home = tmp_path / "real-home"
    profile_path = real_home / "profile.toml"
    workspace_root = tmp_path / "workspaces"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    profile = _write_profile(
        profile_path,
        handoff_dir="$HOME/missing-handoff",
        workspace_root=workspace_root,
    )

    result = _run_complete(profile, "DJ-T4", os.environ.copy())

    assert result.returncode == 0, result.stderr
    assert "no incoming planner handoffs found" in result.stdout
