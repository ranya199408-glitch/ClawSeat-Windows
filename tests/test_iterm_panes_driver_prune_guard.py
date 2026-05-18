from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))


class _FakeSession:
    def __init__(self, sid: str = "s0") -> None:
        self.session_id = sid
        self.name = ""
        self.sent_text: list[str] = []
        self.variables: dict[str, str] = {}
        self._children: list["_FakeSession"] = []

    async def async_split_pane(self, *, vertical: bool = False) -> "_FakeSession | None":
        del vertical
        new = _FakeSession(sid=f"{self.session_id}.{len(self._children)}")
        self._children.append(new)
        return new

    async def async_set_name(self, name: str) -> None:
        self.name = name

    async def async_set_variable(self, key: str, value: str) -> None:
        self.variables[key] = value

    async def async_get_variable(self, key: str) -> str:
        return self.variables.get(key, "")

    async def async_send_text(self, text: str) -> None:
        self.sent_text.append(text)


class _FakeTab:
    def __init__(self, session: _FakeSession) -> None:
        self.current_session = session
        self.title = ""
        self.closed = False

    async def async_set_title(self, title: str) -> None:
        self.title = title

    async def async_invoke_function(self, invocation: str, timeout: float = -1):
        del timeout
        if invocation == "iterm2.get_tab_title()":
            return self.title or self.current_session.name
        return ""

    async def async_close(self, force: bool = False) -> None:
        del force
        self.closed = True


class _FakeWindow:
    def __init__(self) -> None:
        root = _FakeSession(sid="root")
        root.closed = False  # type: ignore[attr-defined]
        self.current_tab = _FakeTab(root)
        self.tabs = [self.current_tab]
        self.window_id = "w-fake"
        self.title = ""
        self.closed = False
        self.variables: dict[str, str] = {}

    async def async_set_title(self, title: str) -> None:
        self.title = title

    async def async_set_variable(self, key: str, value: str) -> None:
        self.variables[key] = value

    async def async_get_variable(self, key: str):
        return self.variables.get(key, "")

    async def async_create_tab(self):
        tab = _FakeTab(_FakeSession(sid=f"tab{len(self.tabs)}"))
        self.tabs.append(tab)
        return tab

    async def async_close(self, force: bool = False) -> None:
        del force
        self.closed = True


class _FakeWindowFactory:
    windows: list[_FakeWindow] = []

    @classmethod
    async def async_get_app(cls, connection):
        del connection
        return types.SimpleNamespace(windows=list(cls.windows))


_fake_iterm2 = types.ModuleType("iterm2")
_fake_iterm2.async_get_app = _FakeWindowFactory.async_get_app  # type: ignore[attr-defined]
_fake_iterm2.run_until_complete = lambda coro: asyncio.run(coro(None))  # type: ignore[attr-defined]
async def _fake_async_window_create(connection: object) -> _FakeWindow:
    del connection
    return _FakeWindow()


_FakeWindowClass = type("Window", (), {"async_create": classmethod(_fake_async_window_create)})  # type: ignore[misc]
_fake_iterm2.Window = _FakeWindowClass  # type: ignore[attr-defined]
sys.modules["iterm2"] = _fake_iterm2

import core.scripts.iterm_panes_driver as driver  # noqa: E402


@pytest.fixture(autouse=True)
def _use_local_fake_iterm2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver, "iterm2", _fake_iterm2)


def _memory_session_project_tab() -> _FakeWindow:
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.name = "install-memory-claude"
    existing.current_tab.current_session.variables["user.tab_name"] = "install"
    existing.current_tab.title = "install"
    return existing


def test_prune_guard_skips_live_memory_tab(capsys: pytest.CaptureFixture[str]) -> None:
    existing = _memory_session_project_tab()
    _FakeWindowFactory.windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "install", "command": "sh -c true"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    validated, error = driver._validate_payload(payload)
    assert error is None and validated is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=validated))

    assert result["status"] == "ok"
    assert result["tabs_pruned"] == 0
    assert existing.current_tab.closed is False
    assert "INFO: prune skipped live memory tab=install" in capsys.readouterr().err


def test_prune_guard_does_not_skip_dead_memory_tab_without_matching_suffix():
    existing = _memory_session_project_tab()
    existing.current_tab.current_session.name = "install-memory-old"
    _FakeWindowFactory.windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "install", "command": "tmux attach -t '=install-memory-claude'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    validated, error = driver._validate_payload(payload)
    assert error is None and validated is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=validated))

    assert result["status"] == "ok"
    assert result["tabs_pruned"] == 1
    assert existing.current_tab.closed is True
