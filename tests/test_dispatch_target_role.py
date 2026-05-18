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
project_name = "dispatch-demo"
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

[dynamic_roster]
materialized_seats = ["planner", "builder"]
""",
        encoding="utf-8",
    )
    return profile


def _dispatch(profile: Path, db_path: Path, role: str, task_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_DISPATCH),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target-role",
            role,
            "--task-id",
            task_id,
            "--title",
            "demo",
            "--objective",
            "demo",
            "--test-policy",
            "UPDATE",
            "--reply-to",
            "planner",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAWSEAT_STATE_DB": str(db_path)},
        check=False,
    )


def test_dispatch_target_role_succeeds_with_registered_seat(tmp_path: Path) -> None:
    from core.lib.state import Seat, open_db, upsert_seat

    db_path = tmp_path / "state.db"
    profile = _profile(tmp_path)
    with open_db(db_path) as conn:
        upsert_seat(
            conn,
            Seat(
                project="dispatch-demo",
                seat_id="builder",
                role="builder",
                tool="claude",
                auth_mode="oauth",
                provider="anthropic",
                status="live",
            ),
        )

    result = _dispatch(profile, db_path, "builder", "TARGET-ROLE-OK")

    assert result.returncode == 0, result.stderr
    assert "target-role resolved: builder -> builder" in result.stderr
    assert len(list((tmp_path / "handoffs").glob("TARGET-ROLE-OK*.json"))) == 1


def test_dispatch_target_role_error_has_reconcile_hint(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    result = _dispatch(profile, tmp_path / "state.db", "planner", "TARGET-ROLE-MISS")

    assert result.returncode == 3
    assert "seat_needed: no live seat with role='planner' in project='dispatch-demo'" in result.stderr
    assert "agent_admin.py session reconcile --project dispatch-demo" in result.stderr
    assert "--target <seat_id>" in result.stderr
