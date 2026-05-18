from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_DISPATCH = _REPO / "core" / "skills" / "gstack-harness" / "scripts" / "dispatch_task.py"


def _profile(tmp_path: Path) -> Path:
    tasks = tmp_path / "tasks"
    handoffs = tmp_path / "handoffs"
    workspace = tmp_path / "workspaces"
    for path in (tasks / "planner", tasks / "builder", handoffs, workspace):
        path.mkdir(parents=True, exist_ok=True)
    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test"
template_name = "gstack-harness"
project_name = "docs-gate"
repo_root = "{tmp_path}"
tasks_root = "{tasks}"
workspace_root = "{workspace}"
handoff_dir = "{handoffs}"
project_doc = "{tasks}/PROJECT.md"
tasks_doc = "{tasks}/TASKS.md"
status_doc = "{tasks}/STATUS.md"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
heartbeat_receipt = "{workspace}/koder/HEARTBEAT_RECEIPT.toml"
seats = ["planner", "builder"]
heartbeat_seats = []
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_owner = "koder"
heartbeat_transport = "tmux"

[seat_roles]
planner = "planner"
builder = "builder"
""",
        encoding="utf-8",
    )
    return profile


def _dispatch(profile: Path, task_type: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_DISPATCH),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target",
            "builder",
            "--task-id",
            f"TASK-{task_type}",
            "--title",
            "demo",
            "--objective",
            "demo",
            "--test-policy",
            "UPDATE",
            "--reply-to",
            "planner",
            "--task-type",
            task_type,
            "--no-notify",
            *extra,
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAWSEAT_STATE_DB": str(profile.parent / "state.db")},
        check=False,
    )


def test_external_integration_requires_docs_flag(tmp_path: Path) -> None:
    result = _dispatch(_profile(tmp_path), "external-integration")

    assert result.returncode == 2
    assert "external-integration task requires --docs-consulted" in result.stderr


def test_non_external_integration_does_not_require_docs_flag(tmp_path: Path) -> None:
    result = _dispatch(_profile(tmp_path), "implementation")

    assert result.returncode == 0, result.stderr
