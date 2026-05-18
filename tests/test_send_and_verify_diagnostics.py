"""Diagnostics tests for send-and-verify.sh (T3 bundle-A).

All tests inject fake binaries via TMUX_BIN / AGENTCTL_BIN env vars so
they run without a real tmux process or live session.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "core/shell-scripts/send-and-verify.sh"


def _run(args: list[str], extra_env: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("CLAWSEAT_PROJECT", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([str(SCRIPT)] + args, capture_output=True, text=True, env=env)


def _make_fake_agentctl(tmp_path: Path, *, return_empty: bool = False) -> str:
    """Mock agentctl: echoes seat name back, or returns empty string (exit 0)."""
    p = tmp_path / "mock_agentctl.sh"
    if return_empty:
        p.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    else:
        p.write_text(
            "#!/usr/bin/env bash\n"
            "shift  # skip 'session-name'\n"
            "while [ $# -gt 0 ]; do\n"
            "  case \"$1\" in --project) shift 2 ;; *) echo \"$1\"; exit 0 ;; esac\n"
            "done\n"
            "exit 0\n",
            encoding="utf-8",
        )
    p.chmod(0o755)
    return str(p)


def _make_fake_tmux(tmp_path: Path, *, has_session_rc: int = 0, subdir: str = "fakebin") -> str:
    """Fake tmux binary: has-session returns has_session_rc; all other cmds succeed."""
    d = tmp_path / subdir
    d.mkdir(exist_ok=True)
    p = d / "tmux"
    p.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$1\" in\n"
        f"  has-session) exit {has_session_rc} ;;\n"
        "  send-keys) exit 0 ;;\n"
        "  list-sessions) echo 'mock: 0 active sessions'; exit 0 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    p.chmod(0o755)
    return str(p)


# ─── TMUX_MISSING ────────────────────────────────────────────────────────────

def test_tmux_missing_exit_code_is_1(tmp_path, isolated_tasks_dir):
    """TMUX_MISSING: rc=1."""
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": "/nonexistent_tmux_binary", "AGENTCTL_BIN": fake_ctl},
    )
    assert result.returncode == 1


def test_tmux_missing_stdout_keyword(tmp_path, isolated_tasks_dir):
    """TMUX_MISSING: 'TMUX_MISSING' appears in stdout for backward compat."""
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": "/nonexistent_tmux_binary", "AGENTCTL_BIN": fake_ctl},
    )
    assert "TMUX_MISSING" in result.stdout


def test_tmux_missing_stderr_reason_and_fix(tmp_path, isolated_tasks_dir):
    """TMUX_MISSING: stderr has reason, searched paths, PATH, and fix hint."""
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": "/nonexistent_tmux_binary", "AGENTCTL_BIN": fake_ctl},
    )
    assert "reason" in result.stderr
    assert "fix" in result.stderr
    assert "PATH" in result.stderr or "searched" in result.stderr


# ─── SESSION_NOT_FOUND ───────────────────────────────────────────────────────

def test_session_not_found_exit_code_is_1(tmp_path, isolated_tasks_dir):
    """SESSION_NOT_FOUND: rc=1."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=0)
    fake_ctl = _make_fake_agentctl(tmp_path, return_empty=True)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert result.returncode == 1


def test_session_not_found_stdout_keyword(tmp_path):
    """SESSION_NOT_FOUND: 'SESSION_NOT_FOUND' appears in stdout."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=0)
    fake_ctl = _make_fake_agentctl(tmp_path, return_empty=True)
    result = _run(
        ["--project", "myproj", "myseat", "hello"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert "SESSION_NOT_FOUND" in result.stdout


def test_session_not_found_stderr_fields(tmp_path):
    """SESSION_NOT_FOUND: stderr has reason, requested_seat, agentctl_bin, fix."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=0)
    fake_ctl = _make_fake_agentctl(tmp_path, return_empty=True)
    result = _run(
        ["--project", "testproject", "testseat", "hello"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert "reason" in result.stderr
    assert "testseat" in result.stderr
    assert "fix" in result.stderr
    assert "testproject" in result.stderr or "testproject" in result.stdout


# ─── SESSION_DEAD ────────────────────────────────────────────────────────────

def test_session_dead_exit_code_is_1(tmp_path, isolated_tasks_dir):
    """SESSION_DEAD: rc=1."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=1)
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert result.returncode == 1


def test_session_dead_stdout_keyword(tmp_path, isolated_tasks_dir):
    """SESSION_DEAD: 'SESSION_DEAD' appears in stdout for backward compat."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=1, subdir="deadbin")
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert "SESSION_DEAD" in result.stdout


def test_session_dead_stderr_reason_tmux_fix(tmp_path, isolated_tasks_dir):
    """SESSION_DEAD: stderr has reason, tmux_bin, session name, fix hint."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=1, subdir="deadbin2")
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert "reason" in result.stderr
    assert "tmux_bin" in result.stderr
    assert "fix" in result.stderr


# ─── SENT success ────────────────────────────────────────────────────────────

def test_sent_success_exit_0(tmp_path, isolated_tasks_dir):
    """Successful send: rc=0."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=0)
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello world"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert result.returncode == 0


def test_sent_success_stdout_format(tmp_path, isolated_tasks_dir):
    """Successful send: stdout starts with 'SENT: <session>'."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=0, subdir="sentbin")
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello world"],
        {"TMUX_BIN": fake_tmux, "AGENTCTL_BIN": fake_ctl},
    )
    assert "SENT: myseat" in result.stdout


# ─── Verbose / debug mode ────────────────────────────────────────────────────

def test_verbose_debug_session_dead_adds_session_list(tmp_path, isolated_tasks_dir):
    """CLAWSEAT_SEND_VERIFY_DEBUG=1: SESSION_DEAD stderr includes tmux_sessions field."""
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=1, subdir="debugbin")
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {
            "TMUX_BIN": fake_tmux,
            "AGENTCTL_BIN": fake_ctl,
            "CLAWSEAT_SEND_VERIFY_DEBUG": "1",
        },
    )
    assert result.returncode == 1
    assert "tmux_sessions" in result.stderr


def test_agents_tasks_root_override_drives_multi_project_guard(tmp_path):
    tasks_root = tmp_path / "tasks"
    for name in ("fixture-a", "fixture-b"):
        project_dir = tasks_root / name
        project_dir.mkdir(parents=True)
        (project_dir / "PROJECT_BINDING.toml").write_text(f'project = "{name}"\n', encoding="utf-8")
    fake_tmux = _make_fake_tmux(tmp_path, has_session_rc=0)
    fake_ctl = _make_fake_agentctl(tmp_path)
    result = _run(
        ["myseat", "hello"],
        {
            "TMUX_BIN": fake_tmux,
            "AGENTCTL_BIN": fake_ctl,
            "AGENTS_TASKS_ROOT": str(tasks_root),
            "CLAWSEAT_SEND_ALLOW_NO_PROJECT": "0",
        },
    )
    assert result.returncode == 3
    assert "PROJECT_REQUIRED" in result.stderr
    assert f"tasks_dir: {tasks_root}" in result.stderr


def test_isolated_tasks_dir_fixture_sets_clean_tasks_root(isolated_tasks_dir):
    assert os.environ["AGENTS_TASKS_ROOT"] == str(isolated_tasks_dir)


# ─── Param error ─────────────────────────────────────────────────────────────

def test_param_error_no_args_exit_1():
    """No args: usage error, rc=1."""
    result = _run([])
    assert result.returncode == 1


def test_param_error_no_message_exit_1():
    """Session given but message missing: usage error, rc=1."""
    result = _run(["only-session"])
    assert result.returncode == 1
