from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_DISPATCH = _SCRIPTS / "dispatch_task.py"


def _status_doc() -> str:
    return (
        "# test — STATUS\n\n"
        "## phase\n\n"
        "phase=ready\n\n"
        "## dispatch log (append-only, last 20)\n\n"
    )


def _make_profile(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    tasks = tmp_path / "tasks" / "install"
    handoffs = tasks / "patrol" / "handoffs"
    workspace = tmp_path / "workspaces" / "install"
    status = tasks / "STATUS.md"
    (tasks / "builder").mkdir(parents=True, exist_ok=True)
    handoffs.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    status.write_text(_status_doc(), encoding="utf-8")

    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "install"
repo_root = "{_REPO}"
tasks_root = "{tasks}"
project_doc = "{tasks / "PROJECT.md"}"
tasks_doc = "{tasks / "TASKS.md"}"
status_doc = "{status}"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
workspace_root = "{workspace}"
handoff_dir = "{handoffs}"
heartbeat_owner = "koder"
heartbeat_transport = "tmux"
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_receipt = "{workspace / "koder" / "HEARTBEAT_RECEIPT.toml"}"
seats = ["planner", "builder"]
heartbeat_seats = []

[seat_roles]
planner = "planner-dispatcher"
builder = "builder"

[dynamic_roster]
materialized_seats = ["planner", "builder"]
runtime_seats = ["planner", "builder"]
""",
        encoding="utf-8",
    )
    return profile, tasks / "builder" / "TODO.md", handoffs, status


def _dispatch_cmd(profile: Path, task_id: str, *extra: str) -> list[str]:
    return [
        sys.executable,
        str(_DISPATCH),
        "--profile",
        str(profile),
        "--source",
        "planner",
        "--target",
        "builder",
        "--task-id",
        task_id,
        "--title",
        f"test {task_id}",
        "--objective",
        "no-op objective",
        *extra,
        "--reply-to",
        "planner",
        "--no-notify",
    ]


@pytest.mark.parametrize("policy", ["UPDATE", "FREEZE", "EXTEND", "N/A"])
def test_dispatch_accepts_test_policy_and_writes_outputs(tmp_path: Path, policy: str) -> None:
    profile, todo, handoffs, status = _make_profile(tmp_path)
    task_id = f"policy-{policy.replace('/', 'NA').lower()}"

    result = subprocess.run(
        _dispatch_cmd(profile, task_id, "--test-policy", policy),
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )

    assert result.returncode == 0, result.stderr
    todo_lines = todo.read_text(encoding="utf-8").splitlines()
    correlation_idx = next(
        idx for idx, line in enumerate(todo_lines) if line.startswith("correlation_id: ")
    )
    assert todo_lines[correlation_idx + 1] == f"test_policy: {policy}"
    assert todo_lines[correlation_idx + 2] == ""
    receipt = json.loads((handoffs / f"{task_id}__planner__builder.json").read_text(encoding="utf-8"))
    assert receipt["test_policy"] == policy
    status_lines = [
        line for line in status.read_text(encoding="utf-8").splitlines()
        if f"planner dispatched {task_id} to builder" in line
    ]
    assert status_lines
    assert status_lines[-1].endswith(f" test_policy={policy}")


def test_dispatch_requires_test_policy(tmp_path: Path) -> None:
    profile, _, _, _ = _make_profile(tmp_path)

    result = subprocess.run(
        _dispatch_cmd(profile, "missing-policy"),
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )

    assert result.returncode != 0
    assert "--test-policy" in result.stderr
    assert "required" in result.stderr


def test_dispatch_rejects_invalid_test_policy(tmp_path: Path) -> None:
    profile, _, _, _ = _make_profile(tmp_path)

    result = subprocess.run(
        _dispatch_cmd(profile, "bad-policy", "--test-policy", "YOLO"),
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
    assert "YOLO" in result.stderr
