from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin  # noqa: E402
import agent_admin_window  # noqa: E402


class _FakeSession:
    def __init__(self, seat_id: str):
        self._seat_id = seat_id
        self.name = seat_id
        self.sent_text: list[str] = []

    async def async_get_variable(self, name: str) -> str:
        if name == "user.seat_id":
            return self._seat_id
        return ""

    async def async_send_text(self, text: str) -> None:
        self.sent_text.append(text)

    async def async_activate(self) -> None:
        return None


class _FakeTab:
    def __init__(self, sessions: list[_FakeSession]):
        self.sessions = sessions


class _FakeWindow:
    def __init__(self, title: str, sessions: list[_FakeSession]):
        self.title = title
        self.tabs = [_FakeTab(sessions)]


class _FakeApp:
    def __init__(self, windows: list[_FakeWindow]):
        self.windows = windows


def _install_fake_iterm(monkeypatch: pytest.MonkeyPatch, app: _FakeApp) -> None:
    async def _async_get_app(_connection):
        return app

    def _run_until_complete(main, retry=True):  # noqa: ARG001
        return asyncio.run(main(None))

    monkeypatch.setitem(
        sys.modules,
        "iterm2",
        SimpleNamespace(async_get_app=_async_get_app, run_until_complete=_run_until_complete),
    )


def test_parser_registers_reseed_pane() -> None:
    parser = agent_admin.build_parser()
    args = parser.parse_args(["window", "reseed-pane", "reviewer", "--project", "install"])

    assert args.command == "window"
    assert args.window_command == "reseed-pane"
    assert args.seat == "reviewer"
    assert args.project == "install"


def test_reseed_pane_sends_interrupt_and_writes_wait_command(monkeypatch: pytest.MonkeyPatch) -> None:
    reviewer = _FakeSession("reviewer")
    _install_fake_iterm(monkeypatch, _FakeApp([_FakeWindow("clawseat-install", [reviewer])]))
    scripts: list[str] = []
    monkeypatch.setattr(agent_admin_window, "osascript", scripts.append)

    project = SimpleNamespace(name="install")
    result = agent_admin_window.reseed_pane(project, "reviewer")

    assert result == {"status": "ok", "project": "install", "seat_id": "reviewer"}
    assert reviewer.sent_text == ["\x03"]
    assert len(scripts) == 1
    assert 'tell application "iTerm2"' in scripts[0]
    assert 'if (seatName as text) is "reviewer"' in scripts[0]
    assert f'tell s to write text "bash {agent_admin_window._WAIT_FOR_SEAT_SCRIPT} install reviewer"' in scripts[0]


def test_reseed_pane_raises_when_seat_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_iterm(
        monkeypatch,
        _FakeApp([_FakeWindow("clawseat-install", [_FakeSession("builder")])]),
    )

    with pytest.raises(agent_admin_window.SeatNotFoundInWindow, match="reviewer"):
        agent_admin_window.reseed_pane(SimpleNamespace(name="install"), "reviewer")


def test_reseed_pane_rejects_ancestor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_iterm(monkeypatch, _FakeApp([]))

    with pytest.raises(agent_admin_window.AgentAdminWindowError, match="cannot reseed primary seat pane"):
        agent_admin_window.reseed_pane(SimpleNamespace(name="install"), "ancestor")
