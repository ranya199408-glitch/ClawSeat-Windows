from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_AGENT_ADMIN = _REPO / "core" / "scripts" / "agent_admin.py"


def _run_agent_admin(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "CLAWSEAT_SUPPRESS_TOOL_BIN_WARNING": "1",
    }
    return subprocess.run(
        [sys.executable, str(_AGENT_ADMIN), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_agent_admin_task_create_and_list_pending(tmp_path: Path) -> None:
    created = _run_agent_admin(
        tmp_path,
        "task",
        "create",
        "demo-task",
        "--project",
        "demo",
        "--workflow-template",
        "basic",
    )
    assert created.returncode == 0, created.stderr

    workflow = tmp_path / "home" / ".agents" / "tasks" / "demo" / "demo-task" / "workflow.md"
    status = workflow.parent / "STATUS.md"
    assert workflow.exists()
    assert status.exists()
    workflow.write_text(
        """# Workflow: demo-task

## Step 1: setup
owner_role: planner
status: done
prereq: []

## Step 2: implement
owner_role: builder
status: pending
prereq: [setup]

## Step 3: review
owner_role: reviewer
status: pending
prereq: [implement]
""",
        encoding="utf-8",
    )

    listed = _run_agent_admin(
        tmp_path,
        "task",
        "list-pending",
        "--project",
        "demo",
        "--owner-role",
        "builder",
    )
    assert listed.returncode == 0, listed.stderr
    assert listed.stdout.strip() == "demo-task\timplement"

    in_progress = _run_agent_admin(
        tmp_path,
        "task",
        "update-status",
        "demo-task",
        "implement",
        "in_progress",
        "--project",
        "demo",
    )
    assert in_progress.returncode == 0, in_progress.stderr

    done = _run_agent_admin(
        tmp_path,
        "task",
        "update-status",
        "demo-task",
        "implement",
        "done",
        "--project",
        "demo",
    )
    assert done.returncode == 0, done.stderr
    assert "status: done" in workflow.read_text(encoding="utf-8")
