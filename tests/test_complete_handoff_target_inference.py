from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"


def _status_doc() -> str:
    return (
        "# test — STATUS\n\n"
        "## phase\n\n"
        "phase=ready\n\n"
        "## dispatch log (append-only, last 20)\n\n"
    )


def _make_profile(tmp_path: Path) -> tuple[Path, Path]:
    tasks = tmp_path / "tasks"
    handoffs = tmp_path / "handoffs"
    workspaces = tmp_path / "workspaces"
    handoffs.mkdir(parents=True, exist_ok=True)
    workspaces.mkdir(parents=True, exist_ok=True)
    for seat in ("planner", "builder", "memory"):
        (tasks / seat).mkdir(parents=True, exist_ok=True)
        (workspaces / seat).mkdir(parents=True, exist_ok=True)
    (tasks / "STATUS.md").write_text(_status_doc(), encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "test"
repo_root = "{tmp_path}"
tasks_root = "{tasks}"
workspace_root = "{workspaces}"
handoff_dir = "{handoffs}"
project_doc = "{tasks}/PROJECT.md"
tasks_doc = "{tasks}/TASKS.md"
status_doc = "{tasks}/STATUS.md"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
heartbeat_receipt = "{workspaces}/koder/HEARTBEAT_RECEIPT.toml"
seats = ["planner", "builder", "memory"]
heartbeat_seats = []
active_loop_owner = "memory"
default_notify_target = "memory"
heartbeat_owner = "koder"
heartbeat_transport = "tmux"

[seat_roles]
planner = "planner-dispatcher"
builder = "builder"
memory = "memory"

[dynamic_roster]
materialized_seats = ["planner", "builder", "memory"]
""",
        encoding="utf-8",
    )
    return profile, handoffs


def _run_complete(profile: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "complete_handoff.py"),
            "--profile",
            str(profile),
            "--source",
            "planner",
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
        cwd=str(_SCRIPTS),
    )


def test_target_is_inferred_from_dispatch_handoff_reply_to(tmp_path: Path) -> None:
    profile, handoffs = _make_profile(tmp_path)
    task_id = "infer-target"
    incoming = handoffs / f"{task_id}__memory__planner.json"
    incoming.write_text(
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

    result = _run_complete(profile, task_id)

    assert result.returncode == 0, result.stderr
    assert f"completed {task_id} -> memory" in result.stdout
    completion_receipt = handoffs / f"{task_id}__planner__memory.json"
    assert completion_receipt.exists()
    payload = json.loads(completion_receipt.read_text(encoding="utf-8"))
    assert payload["target"] == "memory"


def test_target_inference_fails_without_reply_to_handoff(tmp_path: Path) -> None:
    profile, _ = _make_profile(tmp_path)

    result = _run_complete(profile, "missing-target")

    assert result.returncode != 0
    assert "task_id='missing-target'" in result.stderr
    assert "searched " in result.stderr
    assert "with pattern missing-target__*__planner.json" in result.stderr
