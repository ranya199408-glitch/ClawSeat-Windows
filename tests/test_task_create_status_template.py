from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


_REPO = Path(__file__).resolve().parents[1]
_AGENT_ADMIN = _REPO / "core" / "scripts" / "agent_admin.py"
_DISPATCH = _REPO / "core" / "skills" / "gstack-harness" / "scripts" / "dispatch_task.py"
_DISPATCH_LOG = "## dispatch log (append-only, last 20)"
_DISPATCH_COMMENT = "dispatch_task.py / complete_handoff.py append entries here"


def _profile_text(tmp_path: Path, status: Path) -> str:
    tasks = tmp_path / "home" / ".agents" / "tasks" / "install"
    workspaces = tmp_path / "workspaces" / "install"
    handoffs = tasks / "patrol" / "handoffs"
    handoffs.mkdir(parents=True, exist_ok=True)
    workspaces.mkdir(parents=True, exist_ok=True)
    return f"""\
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
workspace_root = "{workspaces}"
handoff_dir = "{handoffs}"
heartbeat_owner = "koder"
heartbeat_transport = "tmux"
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_receipt = "{workspaces / "koder" / "HEARTBEAT_RECEIPT.toml"}"
seats = ["planner", "builder"]
heartbeat_seats = []

[seat_roles]
planner = "planner-dispatcher"
builder = "builder"

[dynamic_roster]
materialized_seats = ["planner", "builder"]
runtime_seats = ["planner", "builder"]
"""


def _run_task_create(home: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_AGENT_ADMIN),
            "task",
            "create",
            task_id,
            "--project",
            "install",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "CLAWSEAT_REAL_HOME": str(home), "HOME": str(home)},
        check=False,
    )


def _run_dispatch(profile: Path, task_id: str) -> subprocess.CompletedProcess[str]:
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
            task_id,
            "--title",
            f"test {task_id}",
            "--objective",
            "no-op objective",
            "--test-policy",
            "EXTEND",
            "--reply-to",
            "planner",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        cwd=str(_DISPATCH.parent),
        check=False,
    )


def _remove_dispatch_log_section(text: str) -> str:
    return text.split(_DISPATCH_LOG, 1)[0].rstrip() + "\n"


def _audit_dir(profile: Path) -> Path:
    data = tomllib.loads(profile.read_text(encoding="utf-8"))
    return Path(data["handoff_dir"]) / "audit"


def test_task_create_status_template_supports_dispatch_log_append(tmp_path: Path) -> None:
    home = tmp_path / "home"
    task_id = "bd-status-template"
    created = _run_task_create(home, task_id)
    assert created.returncode == 0, created.stderr

    status = home / ".agents" / "tasks" / "install" / task_id / "STATUS.md"
    text = status.read_text(encoding="utf-8")
    assert _DISPATCH_LOG in text
    assert _DISPATCH_COMMENT in text

    profile = tmp_path / "profile.toml"
    profile.write_text(_profile_text(tmp_path, status), encoding="utf-8")
    dispatched = _run_dispatch(profile, "bd-dispatch")
    assert dispatched.returncode == 0, dispatched.stderr
    assert "STATUS.md dispatch log append skipped" not in dispatched.stderr
    assert "planner dispatched bd-dispatch to builder" in status.read_text(encoding="utf-8")


def test_task_create_repairs_missing_status_dispatch_log_and_dispatch_fallback_warns(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    task_id = "bd-status-repair"
    created = _run_task_create(home, task_id)
    assert created.returncode == 0, created.stderr

    status = home / ".agents" / "tasks" / "install" / task_id / "STATUS.md"
    status.write_text(_remove_dispatch_log_section(status.read_text(encoding="utf-8")), encoding="utf-8")

    profile = tmp_path / "profile.toml"
    profile.write_text(_profile_text(tmp_path, status), encoding="utf-8")
    warned = _run_dispatch(profile, "bd-dispatch-missing-section")
    assert warned.returncode == 0
    assert "INFO: STATUS.md dispatch-log section auto-healed" in warned.stderr
    assert "STATUS.md dispatch log append skipped" not in warned.stderr
    assert "planner dispatched bd-dispatch-missing-section to builder" in status.read_text(
        encoding="utf-8"
    )
    audit_files = sorted(_audit_dir(profile).glob("dispatch-log-heal-*.json"))
    assert len(audit_files) == 1
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["task_id"] == "bd-dispatch-missing-section"

    repaired = _run_task_create(home, task_id)
    assert repaired.returncode == 0, repaired.stderr
    repaired_text = status.read_text(encoding="utf-8")
    assert _DISPATCH_LOG in repaired_text
    assert "auto-healed by dispatch_task.py" in repaired_text
