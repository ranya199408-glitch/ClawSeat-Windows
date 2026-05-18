from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
VERIFY_HANDOFF = REPO / "core" / "skills" / "gstack-harness" / "scripts" / "verify_handoff.py"


def _make_profile(tmp_path: Path) -> tuple[Path, Path, Path]:
    tasks_root = tmp_path / "tasks" / "test-project"
    handoff_dir = tasks_root / "patrol" / "handoffs"
    workspace_root = tmp_path / "workspaces" / "test-project"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    for seat in ("planner", "builder"):
        (tasks_root / seat).mkdir(parents=True, exist_ok=True)
        (workspace_root / seat).mkdir(parents=True, exist_ok=True)
    profile = tmp_path / "profile.toml"
    profile.write_text(
        "\n".join(
            [
                'version = 1',
                'profile_name = "test-profile"',
                'template_name = "gstack-harness"',
                'project_name = "test-project"',
                f'repo_root = "{REPO}"',
                f'tasks_root = "{tasks_root}"',
                f'project_doc = "{tasks_root / "PROJECT.md"}"',
                f'tasks_doc = "{tasks_root / "TASKS.md"}"',
                f'status_doc = "{tasks_root / "STATUS.md"}"',
                f'send_script = "{REPO / "core" / "shell-scripts" / "send-and-verify.sh"}"',
                f'status_script = "{tasks_root / "patrol" / "check-status.sh"}"',
                f'patrol_script = "{tasks_root / "patrol" / "patrol-supervisor.sh"}"',
                f'agent_admin = "{REPO / "core" / "scripts" / "agent_admin.py"}"',
                f'workspace_root = "{workspace_root}"',
                f'handoff_dir = "{handoff_dir}"',
                'heartbeat_owner = "koder"',
                'active_loop_owner = "planner"',
                'default_notify_target = "planner"',
                f'heartbeat_receipt = "{workspace_root / "koder" / "HEARTBEAT_RECEIPT.toml"}"',
                'seats = ["planner", "builder"]',
                'heartbeat_seats = []',
                '',
                '[seat_roles]',
                'planner = "planner-dispatcher"',
                'builder = "builder"',
                '',
            ]
        ),
        encoding="utf-8",
    )
    return profile, tasks_root / "builder" / "TODO.md", handoff_dir


def _seed_handoff_state(todo_path: Path, handoff_dir: Path) -> tuple[Path, Path]:
    task_id = "TASK-1"
    todo_path.write_text(
        "\n".join(
            [
                f"task_id: {task_id}",
                "project: test-project",
                "owner: builder",
                "status: queued",
                "",
                f"Consumed: {task_id} from planner at 2026-05-05T00:00:00Z",
                "",
            ]
        ),
        encoding="utf-8",
    )
    receipt_path = handoff_dir / f"{task_id}__planner__builder.json"
    receipt_path.write_text(
        json.dumps(
            {
                "kind": "dispatch",
                "task_id": task_id,
                "source": "planner",
                "target": "builder",
                "notified_at": "2026-05-05T00:00:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return receipt_path, todo_path


def _run_verify(profile: Path, task_id: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFY_HANDOFF),
            "--profile",
            str(profile),
            "--task-id",
            task_id,
            "--source",
            "planner",
            "--target",
            "builder",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_verify_handoff_reports_healthy_and_idempotent(tmp_path: Path) -> None:
    profile, todo_path, handoff_dir = _make_profile(tmp_path)
    task_id = "TASK-1"
    _seed_handoff_state(todo_path, handoff_dir)

    first = _run_verify(profile, task_id)
    second = _run_verify(profile, task_id)

    assert first == second
    assert first["healthy"] is True
    assert first["assigned"] is True
    assert first["notified"] is True
    assert first["consumed"] is True
    assert first["verdict_valid"] is True
