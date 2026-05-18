from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_service = _HELPERS._make_service
_make_session = _HELPERS._make_session

_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas


def _capture_start_engineer_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    engineer_id: str,
    reset: bool = False,
) -> dict[str, str]:
    sandbox_home = tmp_path / "sandbox-home"
    real_home = tmp_path / "real-home"
    sandbox_home.mkdir(parents=True, exist_ok=True)
    real_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: sandbox_home))
    monkeypatch.delenv("CLAWSEAT_REAL_HOME", raising=False)
    monkeypatch.setenv("AGENT_HOME", str(real_home))

    session = _make_session(
        tmp_path,
        engineer_id=engineer_id,
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    brief_path = real_home / ".agents" / "tasks" / "install" / "patrol" / "handoffs" / "memory-bootstrap.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text("brief\n", encoding="utf-8")

    svc, hooks = _make_service(tmp_path, session)
    launcher_calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(cmd, **kwargs):
        launcher_calls.append((list(cmd), dict(kwargs.get("env", {}))))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    with (
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.start_engineer(session, reset=reset)

    assert launcher_calls, "launcher was not invoked"
    launcher_call = next(
        (call for call in launcher_calls if call[0][:2] == ["bash", hooks.launcher_path]),
        None,
    )
    assert launcher_call is not None, "launcher command was not captured"
    cmd, env = launcher_call
    assert cmd[:2] == ["bash", hooks.launcher_path]
    return env


def test_start_engineer_ancestor_injects_brief_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _capture_start_engineer_env(tmp_path, monkeypatch, engineer_id="ancestor")

    expected_brief = tmp_path / "real-home" / ".agents" / "tasks" / "install" / "patrol" / "handoffs" / "memory-bootstrap.md"
    assert env["CLAWSEAT_MEMORY_BRIEF"] == str(expected_brief)
    assert env["CLAWSEAT_ANCESTOR_BRIEF"] == str(expected_brief)
    assert env["CLAWSEAT_ROOT"] == str(tmp_path / "repo")


def test_start_engineer_memory_injects_brief_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _capture_start_engineer_env(tmp_path, monkeypatch, engineer_id="memory")

    expected_brief = tmp_path / "real-home" / ".agents" / "tasks" / "install" / "patrol" / "handoffs" / "memory-bootstrap.md"
    assert env["CLAWSEAT_MEMORY_BRIEF"] == str(expected_brief)
    assert env["CLAWSEAT_ANCESTOR_BRIEF"] == str(expected_brief)


def test_start_engineer_non_ancestor_does_not_inject_brief_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _capture_start_engineer_env(tmp_path, monkeypatch, engineer_id="planner")

    assert "CLAWSEAT_MEMORY_BRIEF" not in env
    assert "CLAWSEAT_ANCESTOR_BRIEF" not in env


def test_start_engineer_reset_disables_auto_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = _capture_start_engineer_env(tmp_path, monkeypatch, engineer_id="planner", reset=True)

    assert env["REAL_HOME"] == str(tmp_path / "real-home")
    assert env["CLAWSEAT_NO_AUTO_RESUME"] == "1"
