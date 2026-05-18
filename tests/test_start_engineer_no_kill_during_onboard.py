from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers_onboard", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_session = _HELPERS._make_session
_make_service = _HELPERS._make_service

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
import sys
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas  # noqa: E402


def test_start_engineer_does_not_kill_session_when_onboarding_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    session = _make_session(
        tmp_path,
        engineer_id="designer-1",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    svc, hooks = _make_service(tmp_path, session)
    hooks.tmux_has_session.side_effect = [False, True, True]

    tmux_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        tmux_calls.append(list(cmd))
        if cmd[:2] == ["bash", hooks.launcher_path]:
            return subprocess.CompletedProcess(cmd, 1, "", "launcher failed")
        if cmd[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                "Do you trust the files in this folder?\n",
                "",
            )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    svc.start_engineer(session)

    assert not any(cmd[:2] == ["tmux", "kill-session"] for cmd in tmux_calls)
    assert any(cmd[:2] == ["tmux", "set-option"] for cmd in tmux_calls)
