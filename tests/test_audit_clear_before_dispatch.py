"""Tests for the clear-before-dispatch audit helper and dispatch hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_AUDIT = _SCRIPTS / "audit_clear_before_dispatch.py"
_DISPATCH = _SCRIPTS / "dispatch_task.py"


def _write_exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _write_tmux_stub(bin_dir: Path) -> Path:
    return _write_exe(
        bin_dir / "tmux",
        """#!/bin/bash
case "$1" in
  capture-pane)
    if [ "${TMUX_CAPTURE_RC:-0}" != "0" ]; then
      printf '%s\n' "${TMUX_CAPTURE_ERR:-capture-pane failed}" >&2
      exit "${TMUX_CAPTURE_RC}"
    fi
    printf '%b' "${TMUX_CAPTURE_TEXT:-}"
    exit 0
    ;;
  has-session|send-keys)
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""",
    )


def _write_send_stub(bin_dir: Path, log_path: Path) -> Path:
    return _write_exe(
        bin_dir / "send-and-verify.sh",
        f"""#!/bin/bash
printf '%s\n' "$*" >> '{log_path}'
exit 0
""",
    )


def _make_profile(
    tmp_path: Path,
    *,
    send_script: Path,
    repo_root: Path = _REPO,
) -> tuple[Path, Path, Path]:
    tasks = tmp_path / "tasks"
    handoffs = tmp_path / "handoffs"
    workspaces = tmp_path / "workspaces"
    for path in (
        tasks / "planner",
        tasks / "builder",
        handoffs,
        workspaces,
    ):
        path.mkdir(parents=True, exist_ok=True)
    for filename in ("PROJECT.md", "TASKS.md", "STATUS.md"):
        (tasks / filename).write_text("", encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text(
        textwrap.dedent(
            f"""\
            version = 1
            profile_name = "test-profile"
            template_name = "gstack-harness"
            project_name = "install"
            repo_root = "{repo_root}"
            tasks_root = "{tasks}"
            workspace_root = "{workspaces}"
            handoff_dir = "{handoffs}"
            project_doc = "{tasks}/PROJECT.md"
            tasks_doc = "{tasks}/TASKS.md"
            status_doc = "{tasks}/STATUS.md"
            send_script = "{send_script}"
            status_script = "/bin/echo"
            patrol_script = "/bin/echo"
            agent_admin = "/bin/echo"
            heartbeat_receipt = "{workspaces}/koder/HEARTBEAT_RECEIPT.toml"
            seats = ["planner", "builder"]
            heartbeat_seats = []
            active_loop_owner = "planner"
            default_notify_target = "planner"
            heartbeat_owner = "koder"
            heartbeat_transport = "tmux"

            [seat_roles]
            planner = "planner-dispatcher"
            builder = "builder"

            [dynamic_roster]
            materialized_seats = ["planner", "builder"]
            """
        ),
        encoding="utf-8",
    )
    return profile, tasks, handoffs


def _seed_sessions(agent_home: Path) -> None:
    sessions = agent_home / ".agents" / "sessions" / "install"
    for seat, session_name in {
        "planner": "install-planner-claude",
        "builder": "install-builder-claude",
    }.items():
        seat_dir = sessions / seat
        seat_dir.mkdir(parents=True, exist_ok=True)
        (seat_dir / "session.toml").write_text(
            f'session = "{session_name}"\nengineer_id = "{seat}"\n',
            encoding="utf-8",
        )


def _base_env(tmp_path: Path, *, bin_dir: Path) -> dict[str, str]:
    agent_home = tmp_path / "home"
    agent_home.mkdir(parents=True, exist_ok=True)
    _seed_sessions(agent_home)
    return {
        "HOME": str(agent_home),
        "AGENT_HOME": str(agent_home),
        "CLAWSEAT_ROOT": str(_REPO),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
    }


def _audit_cmd(
    profile: Path,
    task_id: str,
    target: str,
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(_AUDIT),
        "--profile",
        str(profile),
        "--task-id",
        task_id,
        "--target",
        target,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)


def _dispatch_cmd(
    profile: Path,
    task_id: str,
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    cmd = [
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
        "test objective",
        "--test-policy",
        "EXTEND",
        "--reply-to",
        "planner",
    ]
    return subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)


def _write_consumed_receipt(handoffs: Path, task_id: str, target: str = "builder") -> Path:
    receipt = handoffs / f"{task_id}__{target}__planner.json.consumed"
    receipt.write_text(
        json.dumps(
            {
                "kind": "completion",
                "task_id": task_id,
                "source": target,
                "target": "planner",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return receipt


def test_gate1_fail_is_not_applicable_and_has_no_warning(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_tmux_stub(bin_dir)
    send_script = _write_send_stub(bin_dir, tmp_path / "send.log")
    profile, _tasks, _handoffs = _make_profile(tmp_path, send_script=send_script)
    env = _base_env(tmp_path, bin_dir=bin_dir)
    env["TMUX_CAPTURE_TEXT"] = "planner idle\nbuilder idle\n"

    result = _audit_cmd(profile, "AUDIT-G1", "builder", env=env)

    assert result.returncode == 2
    assert "gate1_missing" in result.stderr
    assert "[CLEAR-AUDIT-WARNING]" not in result.stderr
    assert not list((_tasks / "finding").glob("*.md"))


def test_gate3_fail_is_not_applicable_and_has_no_warning(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_tmux_stub(bin_dir)
    send_script = _write_send_stub(bin_dir, tmp_path / "send.log")
    profile, tasks, handoffs = _make_profile(tmp_path, send_script=send_script)
    _write_consumed_receipt(handoffs, "AUDIT-G3")
    (tasks / "builder" / "DELIVERY.md").write_text("task_id: AUDIT-G3\n", encoding="utf-8")
    env = _base_env(tmp_path, bin_dir=bin_dir)
    env["TMUX_CAPTURE_TEXT"] = "Thinking\n"

    result = _audit_cmd(profile, "AUDIT-G3", "builder", env=env)

    assert result.returncode == 2
    assert "gate3_busy" in result.stderr
    assert "[CLEAR-AUDIT-WARNING]" not in result.stderr
    assert not list((tasks / "finding").glob("*.md"))


def test_gate1_and_gate3_fail_still_do_not_warn(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_tmux_stub(bin_dir)
    send_script = _write_send_stub(bin_dir, tmp_path / "send.log")
    profile, tasks, _handoffs = _make_profile(tmp_path, send_script=send_script)
    env = _base_env(tmp_path, bin_dir=bin_dir)
    env["TMUX_CAPTURE_TEXT"] = "Thinking\n"

    result = _audit_cmd(profile, "AUDIT-BOTH", "builder", env=env)

    assert result.returncode == 2
    assert "gate1_missing" in result.stderr
    assert "[CLEAR-AUDIT-WARNING]" not in result.stderr
    assert not list((tasks / "finding").glob("*.md"))


def test_gate1_and_gate3_pass_without_clear_emits_warning_and_finding(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_tmux_stub(bin_dir)
    send_log = tmp_path / "send.log"
    send_script = _write_send_stub(bin_dir, send_log)
    profile, tasks, handoffs = _make_profile(tmp_path, send_script=send_script)
    _write_consumed_receipt(handoffs, "AUDIT-WARN")
    (tasks / "builder" / "DELIVERY.md").write_text("task_id: AUDIT-WARN\n", encoding="utf-8")
    env = _base_env(tmp_path, bin_dir=bin_dir)
    env["TMUX_CAPTURE_TEXT"] = "builder idle\nplanner idle\n"
    env["CLAWSEAT_STATE_DB"] = str(tmp_path / "state.db")

    result = _dispatch_cmd(profile, "AUDIT-WARN", env=env)

    assert result.returncode == 0, result.stderr
    assert "[CLEAR-AUDIT-WARNING]" in result.stderr
    finding_files = sorted((tasks / "finding").glob("install-finding-*-clear-violation-AUDIT-WARN.md"))
    assert len(finding_files) == 1
    content = finding_files[0].read_text(encoding="utf-8")
    assert "[CLEAR-AUDIT-WARNING]" in content
    assert "AUDIT-WARN" in content
    log_lines = send_log.read_text(encoding="utf-8").splitlines()
    assert any("install-planner-claude" in line and "[CLEAR-AUDIT-WARNING]" in line for line in log_lines)


def test_gate1_and_gate3_pass_with_clear_is_clean(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_tmux_stub(bin_dir)
    send_script = _write_send_stub(bin_dir, tmp_path / "send.log")
    profile, tasks, handoffs = _make_profile(tmp_path, send_script=send_script)
    _write_consumed_receipt(handoffs, "AUDIT-CLEAR")
    (tasks / "builder" / "DELIVERY.md").write_text("task_id: AUDIT-CLEAR\n", encoding="utf-8")
    env = _base_env(tmp_path, bin_dir=bin_dir)
    env["TMUX_CAPTURE_TEXT"] = "builder idle\n/clear\nplanner idle\n"

    result = _audit_cmd(profile, "AUDIT-CLEAR", "builder", env=env)

    assert result.returncode == 0
    assert "clear-audit: pass" in result.stdout
    assert "[CLEAR-AUDIT-WARNING]" not in result.stderr
    assert not list((tasks / "finding").glob("*.md"))


def test_dispatch_integration_warning_does_not_block_dispatch(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_tmux_stub(bin_dir)
    send_log = tmp_path / "send.log"
    send_script = _write_send_stub(bin_dir, send_log)
    profile, tasks, handoffs = _make_profile(tmp_path, send_script=send_script)
    _write_consumed_receipt(handoffs, "AUDIT-DISPATCH")
    (tasks / "builder" / "DELIVERY.md").write_text("task_id: AUDIT-DISPATCH\n", encoding="utf-8")
    env = _base_env(tmp_path, bin_dir=bin_dir)
    env["TMUX_CAPTURE_TEXT"] = "builder idle\nplanner idle\n"
    env["CLAWSEAT_STATE_DB"] = str(tmp_path / "state.db")

    result = _dispatch_cmd(profile, "AUDIT-DISPATCH", env=env)

    assert result.returncode == 0, result.stderr
    assert "[CLEAR-AUDIT-WARNING]" in result.stderr
    receipt = handoffs / "AUDIT-DISPATCH__planner__builder.json"
    assert receipt.exists()
    finding_files = sorted((tasks / "finding").glob("install-finding-*-clear-violation-AUDIT-DISPATCH.md"))
    assert len(finding_files) == 1
    log_lines = send_log.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) >= 2
    assert any("install-builder-claude" in line for line in log_lines)
    assert any("install-planner-claude" in line and "[CLEAR-AUDIT-WARNING]" in line for line in log_lines)
