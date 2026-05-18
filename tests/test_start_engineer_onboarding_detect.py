from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas  # noqa: E402


@pytest.mark.parametrize(
    "content",
    [
        "Do you trust the files in this folder?",
        "Trust folder",
        "Welcome to Claude Code",
        "authenticate with your browser",
        "https://accounts.google.com",
        "Paste the code",
        "Enter your API key",
    ],
)
def test_is_session_onboarding_detects_known_markers(monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(cmd, 0, content, "")
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    service = aas.SessionService(SimpleNamespace())
    assert service._is_session_onboarding("spawn49-designer") is True


def test_is_session_onboarding_returns_false_for_normal_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(cmd, 0, "shell prompt", "")
        return subprocess.CompletedProcess(cmd, 1, "", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    service = aas.SessionService(SimpleNamespace())
    assert service._is_session_onboarding("spawn49-designer") is False
