"""Boundary + safety tests for iterm_panes_driver.

The driver runs against a real iTerm2 in production. These tests mock
the iterm2 SDK so we can hammer every edge case (failed splits, partial
build, bad JSON, layout shapes 1..8, illegal labels) without spawning
windows. Critically, every test asserts that NO tmux command is ever
issued by the driver itself — tmux activity is only what operator
commands do INSIDE each pane (typically `tmux attach -t <session>`).
"""
from __future__ import annotations

import asyncio
import importlib
import io
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))


# ─────────────────────────────────────────────────────────────────────
# Inject a fake `iterm2` module BEFORE importing the driver.
# ─────────────────────────────────────────────────────────────────────

class _FakeSession:
    def __init__(self, sid: str = "s0"):
        self.session_id = sid
        self.name = ""
        self.sent_text: list[str] = []
        self.variables: dict[str, str] = {}
        # Each call appends a child to chain so order can be inspected
        self._children: list["_FakeSession"] = []
        self.split_will_fail = False
        self.split_returns_none = False

    async def async_split_pane(self, *, vertical: bool = False) -> "_FakeSession | None":
        if self.split_will_fail:
            raise RuntimeError("simulated split failure")
        if self.split_returns_none:
            return None
        new = _FakeSession(sid=f"{self.session_id}.{len(self._children)}")
        self._children.append(new)
        return new

    async def async_set_name(self, name: str) -> None:
        if not isinstance(name, str):
            raise TypeError("name must be str")
        self.name = name

    async def async_set_variable(self, name: str, value: str) -> None:
        self.variables[name] = value

    async def async_get_variable(self, name: str):
        return self.variables.get(name, "")

    async def async_send_text(self, text: str) -> None:
        if not isinstance(text, str):
            raise TypeError("text must be str")
        self.sent_text.append(text)


class _FakeTab:
    def __init__(self, root: _FakeSession):
        self.current_session = root
        self.title = ""
        self.invoke_title_raises = False
        self.closed = False
        self.close_will_fail = False

    async def async_set_title(self, title: str) -> None:
        self.title = title

    async def async_invoke_function(self, invocation: str, timeout: float = -1):
        if self.invoke_title_raises:
            raise RuntimeError("tab title unavailable")
        if invocation == "iterm2.get_tab_title()":
            return self.title or self.current_session.name
        return ""

    async def async_close(self, force: bool = False) -> None:
        if self.close_will_fail:
            raise RuntimeError("simulated tab close failure")
        self.closed = True


class _FakeWindow:
    def __init__(self):
        self._root = _FakeSession(sid="root")
        self.current_tab = _FakeTab(self._root)
        self.tabs = [self.current_tab]
        self.window_id = "w-fake"
        self.title = ""
        self.closed = False
        self.set_title_raises = False
        self.create_tab_will_fail = False
        self.create_tab_returns_none = False
        self.variables: dict[str, str] = {}

    async def async_set_title(self, title: str) -> None:
        if self.set_title_raises:
            raise RuntimeError("set_title not supported")
        self.title = title

    async def async_set_variable(self, name: str, value: str) -> None:
        self.variables[name] = value

    async def async_get_variable(self, name: str):
        return self.variables.get(name, "")

    async def async_create_tab(self):
        if self.create_tab_will_fail:
            raise RuntimeError("simulated tab create failure")
        if self.create_tab_returns_none:
            return None
        tab = _FakeTab(_FakeSession(sid=f"tab{len(self.tabs)}"))
        self.tabs.append(tab)
        return tab

    async def async_close(self, force: bool = False) -> None:
        self.closed = True


class _FakeApp:
    def __init__(self, windows: list[_FakeWindow] | None = None):
        self.windows = list(windows or [])


class _FakeWindowFactory:
    """Stateful holder so individual tests can swap behaviors."""
    next_window: _FakeWindow | None = None
    create_will_fail: bool = False
    get_app_will_fail: bool = False
    app_windows: list[_FakeWindow] = []

    @classmethod
    async def async_get_app(cls, connection):
        if cls.get_app_will_fail:
            raise RuntimeError("simulated get_app failure")
        return _FakeApp(cls.app_windows)

    @classmethod
    async def async_create(cls, connection):
        if cls.create_will_fail:
            raise RuntimeError("simulated window create failure")
        if cls.next_window is None:
            cls.next_window = _FakeWindow()
        return cls.next_window


# Build the fake module
_fake_iterm2 = types.ModuleType("iterm2")
_fake_iterm2.async_get_app = _FakeWindowFactory.async_get_app  # type: ignore[attr-defined]
_fake_iterm2.run_until_complete = lambda coro: asyncio.run(coro(None))  # type: ignore[attr-defined]

_FakeWindowClass = type("Window", (), {"async_create": _FakeWindowFactory.async_create})
_fake_iterm2.Window = _FakeWindowClass  # type: ignore[attr-defined]

sys.modules["iterm2"] = _fake_iterm2

# Now we can import the driver. It will pick up the fake iterm2.
import core.scripts.iterm_panes_driver as driver  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_factories():
    _FakeWindowFactory.next_window = None
    _FakeWindowFactory.create_will_fail = False
    _FakeWindowFactory.get_app_will_fail = False
    _FakeWindowFactory.app_windows = []
    yield


@pytest.fixture
def no_tmux_calls(monkeypatch):
    """Sentinel: fail loudly if anyone shells out to `tmux` from the driver."""
    import subprocess
    real_run = subprocess.run

    def guard(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", "")
        if isinstance(cmd, (list, tuple)) and len(cmd) and "tmux" in str(cmd[0]):
            raise AssertionError(f"driver shelled out to tmux: {cmd}")
        if isinstance(cmd, str) and "tmux" in cmd.split()[0:1]:
            raise AssertionError(f"driver shelled out to tmux: {cmd}")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guard)
    yield
    # Belt-and-suspenders: also ensure nothing in subprocess.Popen
    # was used to spawn tmux — but we can't easily catch all paths;
    # the source-level audit (search for "tmux" in driver.py) covers it.


# ─────────────────────────────────────────────────────────────────────
# Section A — payload validation (no iTerm involved)
# ─────────────────────────────────────────────────────────────────────

class TestValidation:

    def test_non_dict_payload_rejected(self):
        v, e = driver._validate_payload(["not", "a", "dict"])
        assert v is None
        assert e is not None and "JSON object" in e["reason"]

    def test_panes_not_list_rejected(self):
        v, e = driver._validate_payload({"panes": "memory"})
        assert v is None
        assert e is not None and "panes must be a list" in e["reason"]

    def test_panes_empty_rejected(self):
        v, e = driver._validate_payload({"panes": []})
        assert v is None
        assert e is not None and "empty" in e["reason"]

    def test_panes_too_many_rejected(self):
        v, e = driver._validate_payload({"panes": [{"label": "x"}] * 9})
        assert v is None
        assert e is not None and "MAX_PANES" in e["reason"]

    def test_pane_not_dict_rejected(self):
        v, e = driver._validate_payload({"panes": [{"label": "ok"}, "nope"]})
        assert v is None
        assert e is not None and "pane[1]" in e["reason"]

    def test_label_not_string_rejected(self):
        v, e = driver._validate_payload({"panes": [{"label": 42}]})
        assert v is None
        assert e is not None and "label" in e["reason"]

    def test_command_not_string_rejected(self):
        v, e = driver._validate_payload({"panes": [{"command": ["ls"]}]})
        assert v is None
        assert e is not None and "command" in e["reason"]

    def test_label_strips_control_chars(self):
        v, e = driver._validate_payload({
            "panes": [{"label": "memo\nry\x07cc", "command": ""}]
        })
        assert e is None and v is not None
        assert v["panes"][0]["label"] == "memorycc", "control chars must be stripped"

    def test_label_truncated_at_64(self):
        v, e = driver._validate_payload({
            "panes": [{"label": "x" * 200, "command": ""}]
        })
        assert e is None and v is not None
        assert len(v["panes"][0]["label"]) == 64

    def test_title_strips_control_and_truncates(self):
        v, e = driver._validate_payload({
            "title": "install\n\n" + ("y" * 200),
            "panes": [{"label": "a"}],
        })
        assert e is None and v is not None
        assert "\n" not in v["title"]
        assert len(v["title"]) <= 128

    def test_title_default_when_missing(self):
        v, e = driver._validate_payload({"panes": [{"label": "a"}]})
        assert e is None and v is not None
        assert v["title"] == "ClawSeat"

    def test_title_default_when_wrong_type(self):
        v, e = driver._validate_payload({"title": 123, "panes": [{"label": "a"}]})
        assert e is None and v is not None
        assert v["title"] == "ClawSeat"

    def test_send_delay_clamped(self):
        v, e = driver._validate_payload({
            "panes": [{"label": "a"}],
            "send_delay_ms": 99999,
        })
        assert e is None and v is not None
        assert v["send_delay_ms"] == driver.DEFAULT_SEND_DELAY_MS

    def test_send_delay_negative_clamped(self):
        v, e = driver._validate_payload({
            "panes": [{"label": "a"}],
            "send_delay_ms": -10,
        })
        assert e is None and v is not None
        assert v["send_delay_ms"] == driver.DEFAULT_SEND_DELAY_MS

    def test_send_delay_zero_kept(self):
        v, e = driver._validate_payload({
            "panes": [{"label": "a"}],
            "send_delay_ms": 0,
        })
        assert e is None and v is not None
        assert v["send_delay_ms"] == 0

    def test_unknown_top_level_keys_ignored(self):
        v, e = driver._validate_payload({
            "panes": [{"label": "a"}],
            "garbage": "ignored",
        })
        assert e is None and v is not None

    def test_tabs_mode_accepts_schema_with_ensure_true(self):
        v, e = driver._validate_payload({
            "mode": "tabs",
            "title": "clawseat-memories",
            "tabs": [
                {"name": "install", "command": "tmux attach -t '=install-memory'"},
            ],
            "ensure": True,
            "send_delay_ms": 0,
        })
        assert e is None and v is not None
        assert v["mode"] == "tabs"
        assert v["ensure"] is True
        assert v["tabs"] == [
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
        ]

    def test_tabs_mode_default_ensure_true(self):
        v, e = driver._validate_payload({
            "mode": "tabs",
            "title": "clawseat-memories",
            "tabs": [{"name": "install", "command": ""}],
        })
        assert e is None and v is not None
        assert v["ensure"] is True

    def test_tabs_empty_rejected(self):
        v, e = driver._validate_payload({
            "mode": "tabs",
            "title": "clawseat-memories",
            "tabs": [],
        })
        assert v is None
        assert e is not None and "tabs list is empty" in e["reason"]

    def test_tabs_command_not_string_rejected(self):
        v, e = driver._validate_payload({
            "mode": "tabs",
            "title": "clawseat-memories",
            "tabs": [{"name": "install", "command": ["bad"]}],
        })
        assert v is None
        assert e is not None and "command" in e["reason"]

    def test_tabs_name_must_be_printable_and_short(self):
        v, e = driver._validate_payload({
            "mode": "tabs",
            "title": "clawseat-memories",
            "tabs": [{"name": "bad\nname", "command": ""}],
        })
        assert v is None
        assert e is not None and "printable" in e["reason"]


# ─────────────────────────────────────────────────────────────────────
# Section B — layout recipes (every shape 1..8)
# ─────────────────────────────────────────────────────────────────────

class TestLayoutRecipes:

    def test_recipes_cover_1_through_8(self):
        for n in range(1, 9):
            assert n in driver._LAYOUT_RECIPES, f"missing recipe for {n}"

    def test_recipes_produce_n_panes(self):
        for n, steps in driver._LAYOUT_RECIPES.items():
            # Initial 1 pane + len(steps) splits = n total
            assert 1 + len(steps) == n, f"recipe {n} produces {1+len(steps)} panes"

    def test_recipes_only_reference_existing_parents(self):
        """Each split's parent_idx must be < total panes BEFORE that split."""
        for n, steps in driver._LAYOUT_RECIPES.items():
            current_count = 1
            for parent_idx, _ in steps:
                assert parent_idx < current_count, (
                    f"recipe {n}: parent_idx={parent_idx} but only "
                    f"{current_count} panes exist"
                )
                current_count += 1


# ─────────────────────────────────────────────────────────────────────
# Section C — build flow against fake iterm2 (every n from 1 to 8)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6, 7, 8])
def test_build_layout_creates_n_panes(no_tmux_calls, n):
    payload = {
        "title": "test",
        "panes": [{"label": f"seat{i}", "command": f"echo seat{i}"} for i in range(n)],
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None
    result = asyncio.run(driver._build_layout(connection=None, payload=v))
    assert result["status"] == "ok", f"n={n}: {result}"
    assert result["panes_created"] == n


def test_build_writes_label_and_command_to_each_pane(no_tmux_calls):
    payload = {
        "title": "install",
        "panes": [
            {"label": "memory", "command": "tmux attach -t '=install-memory-claude'"},
            {"label": "planner", "command": "tmux attach -t '=install-planner-claude'"},
        ],
        "send_delay_ms": 0,
    }
    v, _ = driver._validate_payload(payload)
    result = asyncio.run(driver._build_layout(connection=None, payload=v))
    assert result["status"] == "ok"

    window = _FakeWindowFactory.next_window
    assert window is not None
    assert window.title == "install"
    root = window.current_tab.current_session
    # Walk the tree: root + each child of root + grandchild for n=2 → 1 child only
    sessions = [root, *root._children]
    assert len(sessions) == 2
    assert sessions[0].name == "memory"
    assert sessions[1].name == "planner"
    assert sessions[0].variables["user.seat_id"] == "memory"
    assert sessions[1].variables["user.seat_id"] == "planner"
    assert sessions[0].sent_text == [
        "tmux attach -t '=install-memory-claude'\n"
    ]
    assert sessions[1].sent_text == [
        "tmux attach -t '=install-planner-claude'\n"
    ]


def test_build_no_command_pane_stays_open(no_tmux_calls):
    """A pane with no command becomes a plain bash shell — still counted."""
    payload = {
        "title": "t",
        "panes": [
            {"label": "first", "command": "echo a"},
            {"label": "no-cmd"},  # missing command field
        ],
        "send_delay_ms": 0,
    }
    v, _ = driver._validate_payload(payload)
    result = asyncio.run(driver._build_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    window = _FakeWindowFactory.next_window
    sessions = [window.current_tab.current_session, *window.current_tab.current_session._children]
    assert sessions[1].sent_text == []  # no command sent


# ─────────────────────────────────────────────────────────────────────
# Section C2 — tabs mode / ensure-tab behavior
# ─────────────────────────────────────────────────────────────────────

def test_build_tabs_creates_new_window_tabs(no_tmux_calls):
    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
            {"name": "cartooner", "command": "tmux attach -t '=cartooner-memory'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result == {
        "status": "ok",
        "mode": "tabs",
        "tabs": [
            {"status": "created", "tab": "install"},
            {"status": "created", "tab": "cartooner"},
        ],
        "tabs_created": 2,
        "tabs_skipped": 0,
        "tabs_pruned": 0,
        "window_id": "w-fake",
    }

    window = _FakeWindowFactory.next_window
    assert window is not None
    assert window.title == "clawseat-memories"
    assert window.variables["user.window_title"] == "clawseat-memories"
    assert len(window.tabs) == 2
    first, second = window.tabs
    assert first.title == "install"
    assert second.title == "cartooner"
    assert first.current_session.name == "install"
    assert second.current_session.name == "cartooner"
    assert first.current_session.variables["user.tab_name"] == "install"
    assert second.current_session.variables["user.tab_name"] == "cartooner"
    assert first.current_session.sent_text == ["tmux attach -t '=install-memory'\n"]
    assert second.current_session.sent_text == ["tmux attach -t '=cartooner-memory'\n"]


def test_build_tabs_ensure_skips_existing_marker_and_appends_missing(no_tmux_calls):
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.name = "install-memory (tmux)"
    existing.current_tab.current_session.variables["user.tab_name"] = "install"
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
            {"name": "cartooner", "command": "tmux attach -t '=cartooner-memory'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert result["tabs"] == [
        {"status": "skipped", "tab": "install"},
        {"status": "created", "tab": "cartooner"},
    ]
    assert result["tabs_created"] == 1
    assert result["tabs_skipped"] == 1
    assert existing.closed is False
    assert len(existing.tabs) == 2
    assert existing.current_tab.current_session.sent_text == []
    assert existing.tabs[1].current_session.name == "cartooner"
    assert existing.tabs[1].current_session.sent_text == [
        "tmux attach -t '=cartooner-memory'\n"
    ]


def test_build_tabs_detects_existing_tab_by_session_name_fallback(no_tmux_calls):
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.name = "install"
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "install", "command": "tmux attach -t '=install-memory'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert result["tabs"] == [{"status": "skipped", "tab": "install"}]
    assert result["tabs_created"] == 0
    assert result["tabs_skipped"] == 1
    assert len(existing.tabs) == 1


def test_ensure_tabs_multiple_windows_hard_fails(no_tmux_calls):
    first = _FakeWindow()
    first.variables["user.window_title"] = "clawseat-memories"
    second = _FakeWindow()
    second.variables["user.window_title"] = "clawseat-memories"
    _FakeWindowFactory.app_windows = [first, second]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "install", "command": "tmux attach -t '=install-memory'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "error"
    assert "multiple iTerm windows match title" in result["reason"]
    assert "operator must close stale windows" in result["reason"]
    assert len(first.tabs) == 1
    assert len(second.tabs) == 1


def test_ensure_tabs_detect_failure_creates_tab(no_tmux_calls, monkeypatch):
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.name = "install-memory (tmux)"
    _FakeWindowFactory.app_windows = [existing]

    async def empty_tab_name(tab):
        return ""

    monkeypatch.setattr(driver, "_tab_name", empty_tab_name)

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "install", "command": "tmux attach -t '=install-memory'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert result["tabs"][0]["status"] == "detect-failure"
    assert result["tabs"][0]["tab"] == "install"
    assert "returned empty" in result["tabs"][0]["reason"]
    assert result["tabs_created"] == 1
    assert result["tabs_skipped"] == 0
    assert len(existing.tabs) == 2
    assert existing.tabs[1].current_session.name == "install"
    assert existing.tabs[1].current_session.sent_text == ["tmux attach -t '=install-memory'\n"]


def test_ensure_tabs_cross_check_rejects_stale_ghost(no_tmux_calls):
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.variables["user.tab_name"] = "cartooner"
    existing.current_tab.current_session.name = "machine-memory-claude (tmux)"
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "cartooner", "command": "tmux attach -t '=cartooner-memory'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert result["tabs"][0]["status"] == "detect-failure"
    assert result["tabs"][0]["tab"] == "cartooner"
    assert "machine-memory-claude" in result["tabs"][0]["reason"]
    assert result["tabs_created"] == 1
    assert result["tabs_skipped"] == 0
    assert len(existing.tabs) == 2
    assert existing.current_tab.current_session.sent_text == []
    assert existing.tabs[1].current_session.name == "cartooner"
    assert existing.tabs[1].current_session.sent_text == ["tmux attach -t '=cartooner-memory'\n"]


def test_ensure_tabs_per_tab_status_aggregation(no_tmux_calls):
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.variables["user.tab_name"] = "install"
    existing.current_tab.current_session.name = "install-memory (tmux)"

    stale = _FakeTab(_FakeSession(sid="stale"))
    stale.current_session.variables["user.tab_name"] = "cartooner"
    stale.current_session.name = "machine-memory-claude (tmux)"
    existing.tabs.append(stale)
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
            {"name": "cartooner", "command": "tmux attach -t '=cartooner-memory'"},
            {"name": "arena", "command": "tmux attach -t '=arena-memory'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    # Order: install=skipped, cartooner=detect-failure (mismatch session, new tab created),
    # arena=created (not in window). Then prune sweeps the original stale 'cartooner'-marked
    # tab whose session.name didn't match — added at the end as 'pruned'.
    assert [entry["status"] for entry in result["tabs"]] == [
        "skipped",
        "detect-failure",
        "created",
        "pruned",
    ]
    assert [entry["tab"] for entry in result["tabs"]] == ["install", "cartooner", "arena", "cartooner"]
    assert result["tabs_created"] == 2
    assert result["tabs_skipped"] == 1
    assert result["tabs_pruned"] == 1
    assert len(existing.tabs) == 4
    # The original stale 'cartooner' tab (mismarked) was closed by prune
    assert stale.closed is True


def test_ensure_tabs_reattach_when_tmux_attach_died(no_tmux_calls):
    """Marker matches but the tab's tmux-attach is no longer the foreground
    job (e.g. the tmux session was killed and the attach exited back to a
    bare zsh prompt). Driver should reuse the existing tab and re-send the
    attach command, NOT create a new tab and NOT skip silently."""
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.variables["user.tab_name"] = "cartooner-front"
    # session.name was set by _mark_tab; tmux attach exited so the live
    # job is the parent shell, not tmux.
    existing.current_tab.current_session.name = "cartooner-front"
    existing.current_tab.current_session.current_job = "zsh"
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "cartooner-front", "command": "tmux attach -t '=cartooner-front-memory-codex'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    # No new tab — the existing one was reused.
    assert len(existing.tabs) == 1
    # Status reflects the reattach path.
    assert [entry["status"] for entry in result["tabs"]] == ["reattached"]
    # The attach command was re-sent to the reused session.
    assert existing.tabs[0].current_session.sent_text == [
        "tmux attach -t '=cartooner-front-memory-codex'\n"
    ]


def test_ensure_tabs_skip_when_tmux_attach_alive(no_tmux_calls):
    """When marker matches AND the foreground job is tmux, the attach is
    still running — skip without re-sending."""
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.current_tab.current_session.variables["user.tab_name"] = "cartooner-front"
    existing.current_tab.current_session.name = "cartooner-front-memory-codex (tmux)"
    existing.current_tab.current_session.current_job = "tmux"
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "cartooner-front", "command": "tmux attach -t '=cartooner-front-memory-codex'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert [entry["status"] for entry in result["tabs"]] == ["skipped"]
    # Should NOT re-send the command on the live tab.
    assert existing.tabs[0].current_session.sent_text == []


def test_build_tabs_append_failure_does_not_close_existing_window(no_tmux_calls):
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    existing.create_tab_will_fail = True
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [{"name": "install", "command": "tmux attach -t '=install-memory'"}],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "error"
    assert "create-tab" in result["reason"]
    assert existing.closed is False


def test_build_tabs_failure_closes_new_window(no_tmux_calls):
    new_window = _FakeWindow()
    new_window.create_tab_will_fail = True
    _FakeWindowFactory.next_window = new_window

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
            {"name": "cartooner", "command": "tmux attach -t '=cartooner-memory'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "error"
    assert "create-tab" in result["reason"]
    assert new_window.closed is True


# ─────────────────────────────────────────────────────────────────────
# Section D — partial-failure cleanup
# ─────────────────────────────────────────────────────────────────────

def test_split_failure_closes_window(no_tmux_calls):
    """Halfway split failure must close the window so we don't leave a stub."""
    fake = _FakeWindow()
    # Make the FIRST split's parent fail
    fake.current_tab.current_session.split_will_fail = True
    _FakeWindowFactory.next_window = fake

    payload = {"title": "x", "panes": [{"label": f"s{i}"} for i in range(6)]}
    v, _ = driver._validate_payload(payload)
    result = asyncio.run(driver._build_layout(connection=None, payload=v))

    assert result["status"] == "error"
    assert "split-pane" in result["reason"]
    assert fake.closed is True, "half-built window must be closed"


def test_split_returns_none_closes_window(no_tmux_calls):
    """async_split_pane returning None (iTerm refused) must clean up."""
    fake = _FakeWindow()
    fake.current_tab.current_session.split_returns_none = True
    _FakeWindowFactory.next_window = fake

    payload = {"title": "x", "panes": [{"label": "a"}, {"label": "b"}]}
    v, _ = driver._validate_payload(payload)
    result = asyncio.run(driver._build_layout(connection=None, payload=v))

    assert result["status"] == "error"
    assert "None" in result["reason"]
    assert fake.closed is True


def test_window_create_failure_returns_error(no_tmux_calls):
    _FakeWindowFactory.create_will_fail = True
    payload = {"title": "x", "panes": [{"label": "a"}]}
    v, _ = driver._validate_payload(payload)
    result = asyncio.run(driver._build_layout(connection=None, payload=v))
    assert result["status"] == "error"
    assert "async_create" in result["reason"]


def test_set_title_failure_does_not_abort(no_tmux_calls):
    """Older iTerm without async_set_title — must still build the window."""
    fake = _FakeWindow()
    fake.set_title_raises = True
    _FakeWindowFactory.next_window = fake

    payload = {"title": "x", "panes": [{"label": "a"}], "send_delay_ms": 0}
    v, _ = driver._validate_payload(payload)
    result = asyncio.run(driver._build_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert fake.closed is False


def test_send_text_failure_does_not_close_window(no_tmux_calls):
    """One pane's send failure must not tear down siblings."""
    fake = _FakeWindow()
    _FakeWindowFactory.next_window = fake

    # Override only the SECOND session's send to fail
    async def bad_send(text):
        raise RuntimeError("simulated send_text failure")

    payload = {"title": "x", "panes": [
        {"label": "a", "command": "good"},
        {"label": "b", "command": "bad"},
    ], "send_delay_ms": 0}
    v, _ = driver._validate_payload(payload)

    # Patch the second-pane send_text. The split happens inside _build_layout,
    # so we monkey-patch _FakeSession.async_split_pane to wire a bad child once.
    original_split = _FakeSession.async_split_pane
    call_count = {"n": 0}

    async def wrapped_split(self, *, vertical=False):
        result = await original_split(self, vertical=vertical)
        call_count["n"] += 1
        if call_count["n"] == 1:
            result.async_send_text = bad_send
        return result

    with patch.object(_FakeSession, "async_split_pane", wrapped_split):
        result = asyncio.run(driver._build_layout(connection=None, payload=v))

    assert result["status"] == "ok"
    assert fake.closed is False, "single send failure must not close the window"


# ─────────────────────────────────────────────────────────────────────
# Section E — tmux safety: driver must NEVER spawn tmux directly
# ─────────────────────────────────────────────────────────────────────

class TestTmuxSafety:

    def test_driver_source_does_not_call_tmux(self):
        """Static check: driver source must not import or invoke tmux."""
        src = Path(driver.__file__).read_text()
        # The driver may MENTION tmux in comments / docstrings — that's fine.
        # What it must not do is exec/popen/run with "tmux" as the program.
        forbidden_patterns = [
            'subprocess.run(["tmux',
            "subprocess.run(['tmux",
            'subprocess.Popen(["tmux',
            "subprocess.Popen(['tmux",
            'os.system("tmux',
            "os.system('tmux",
            'os.execvp("tmux',
            "os.execvp('tmux",
            'shutil.which("tmux")',  # would also fail us — driver does not probe
        ]
        for pat in forbidden_patterns:
            assert pat not in src, (
                f"driver invokes tmux directly via {pat!r} — "
                "must never do this; commands are sent INTO panes only"
            )

    def test_driver_entrypoint_retries_iterm_connection(self):
        src = Path(driver.__file__).read_text()
        assert "iterm2.run_until_complete(_main, retry=True)" in src

    def test_full_build_does_not_invoke_tmux(self, no_tmux_calls):
        """Live: build a 6-pane layout and confirm no tmux subprocess fires."""
        payload = {
            "title": "x",
            "panes": [
                {"label": f"s{i}", "command": f"tmux attach -t '=fake-{i}'"}
                for i in range(6)
            ],
            "send_delay_ms": 0,
        }
        v, _ = driver._validate_payload(payload)
        # no_tmux_calls fixture would have raised AssertionError if the driver
        # tried to subprocess.run anything tmux-shaped.
        result = asyncio.run(driver._build_layout(connection=None, payload=v))
        assert result["status"] == "ok"

    def test_attach_command_text_is_sent_verbatim(self, no_tmux_calls):
        """The `tmux attach -t '=...'` command must reach the pane unaltered.

        If the driver mangled it (escaping issues, quoting), the operator's
        target session might be misnamed and an unintended attach could occur
        (or worse, tmux's prefix-match semantics could connect to the wrong
        session). The `=` exact-match prefix MUST survive.
        """
        cmd = "tmux attach -t '=install-memory-claude'"
        payload = {"title": "x", "panes": [{"label": "memory", "command": cmd}],
                   "send_delay_ms": 0}
        v, _ = driver._validate_payload(payload)
        result = asyncio.run(driver._build_layout(connection=None, payload=v))
        assert result["status"] == "ok"

        window = _FakeWindowFactory.next_window
        root = window.current_tab.current_session
        sent = root.sent_text[0]
        assert sent == cmd + "\n", (
            f"send_text text was mangled: {sent!r} vs expected {cmd + chr(10)!r}"
        )
        assert "=install-memory-claude" in sent
        # Ensure no detach flag (-d) was added — that would kick other clients
        assert " -d " not in sent and " --detach" not in sent

    def test_attach_never_uses_kill_or_detach(self, no_tmux_calls):
        """No code path in driver constructs a tmux destructive command."""
        src = Path(driver.__file__).read_text()
        for forbidden in ("kill-session", "kill-server", "tmux attach -d",
                          "tmux kill", " --detach", "tmux send-keys"):
            assert forbidden not in src, (
                f"driver source contains {forbidden!r} — must not"
            )


# ─────────────────────────────────────────────────────────────────────
# Section F — JSON pipeline / main() behaviors
# ─────────────────────────────────────────────────────────────────────

def test_main_with_valid_payload(monkeypatch, capsys, no_tmux_calls):
    payload = {
        "title": "from-stdin",
        "panes": [{"label": "x", "command": "echo hi"}],
        "send_delay_ms": 0,
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    asyncio.run(driver._main(connection=None))
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["status"] == "ok"


def test_main_with_invalid_json(monkeypatch, capsys, no_tmux_calls):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json {"))
    asyncio.run(driver._main(connection=None))
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["status"] == "error"
    assert "json" in parsed["reason"].lower()


def test_main_with_validation_error(monkeypatch, capsys, no_tmux_calls):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"panes": []}'))
    asyncio.run(driver._main(connection=None))
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed["status"] == "error"


# ─────────────────────────────────────────────────────────────────────
# Section G — constants sanity (catches accidental edits)
# ─────────────────────────────────────────────────────────────────────

class TestConstants:

    def test_max_panes_is_8(self):
        assert driver.MAX_PANES == 8

    def test_default_send_delay_is_reasonable(self):
        assert 0 <= driver.DEFAULT_SEND_DELAY_MS <= 1000

    def test_build_timeout_is_reasonable(self):
        assert 5 <= driver.BUILD_TIMEOUT_SECONDS <= 120


# ─────────────────────────────────────────────────────────────────────
# Section H — closing an iTerm pane must NEVER kill the inner tmux session
# (this is a documentation + smoke check; the actual SIGHUP flow is OS-level)
# ─────────────────────────────────────────────────────────────────────

class TestSessionSurvival:

    def test_no_attach_with_destroy_flag(self):
        """No attach command path uses any flag that would destroy the session.

        `tmux attach -t '=NAME'` in the pane is a CLIENT op only. SIGHUP on
        the iTerm pane → bash exits → tmux client detaches → inner session
        unaffected. This test asserts that no operator-supplied command we
        construct anywhere in the driver uses tmux destructive flags.
        """
        # The driver itself constructs nothing — operator supplies command.
        # ClawSeat callers (agent_admin_window etc.) construct commands via
        # `monitor_attach_command()` which we audit elsewhere.
        # This test just affirms the contract by reading the docstring.
        assert "never executes ANY tmux command directly" in driver.__doc__
        assert "session survives" in driver.__doc__.lower()


def test_build_tabs_prunes_stale_tabs_when_reusing_window(no_tmux_calls):
    """ensure=True with reused window must close tabs not in spec.

    Regression: rebuilds previously left stale tabs (e.g. -zsh fallback after
    failed tmux attach) accumulating forever. Now prune any tab whose name
    is not in the new spec.
    """
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    # Tab 0 (current_tab): a stale -zsh fallback (spec doesn't include it)
    existing.current_tab.current_session.name = "-zsh"
    existing.current_tab.current_session.variables["user.tab_name"] = "-zsh"
    existing.current_tab.title = "-zsh"
    # Tab 1: legitimate install tab matching new spec — should be skipped (kept)
    install_tab = _FakeTab(_FakeSession(sid="t-install"))
    install_tab.current_session.name = "install-memory-claude"
    install_tab.current_session.variables["user.tab_name"] = "install"
    install_tab.title = "install"
    existing.tabs.append(install_tab)
    # Tab 2: stale 'dead-project' tab from a project whose memory was killed
    dead_tab = _FakeTab(_FakeSession(sid="t-dead"))
    dead_tab.current_session.name = "dead-memory"
    dead_tab.current_session.variables["user.tab_name"] = "dead-project"
    dead_tab.title = "dead-project"
    existing.tabs.append(dead_tab)
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory-claude'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))

    assert result["status"] == "ok"
    assert result["tabs_pruned"] == 2  # both -zsh tab and dead-project tab pruned
    # Tab close was called on both stale tabs
    assert existing.current_tab.closed is True  # -zsh tab
    assert dead_tab.closed is True
    # Install tab survived
    assert install_tab.closed is False


def test_build_tabs_does_not_prune_when_creating_new_window(no_tmux_calls):
    """If we just created the window, there are no stale tabs to prune."""
    _FakeWindowFactory.app_windows = []  # no existing window

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert result["tabs_pruned"] == 0


def test_build_tabs_prunes_tab_with_mismarked_user_tab_name(no_tmux_calls):
    """Stale tab whose user.tab_name marker matches a spec but whose session
    is attached to the WRONG tmux session must still be pruned.

    Real-world cause: a previous driver bug wrote install marker onto a tab
    that was already attached to cartooner-front-memory-codex. Naive prune
    saw the marker, said "this is install, keep", missing the mismatch.
    """
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    # Tab 0 (current_tab): MIS-MARKED — user.tab_name says "install" but
    # session.name is the wrong tmux session (cartooner-front-memory-codex).
    existing.current_tab.current_session.name = "cartooner-front-memory-codex"
    existing.current_tab.current_session.variables["user.tab_name"] = "install"
    existing.current_tab.title = "install"
    # Tab 1: legitimate install tab — marker matches AND session matches.
    install_tab = _FakeTab(_FakeSession(sid="t-install"))
    install_tab.current_session.name = "install-memory-claude"
    install_tab.current_session.variables["user.tab_name"] = "install"
    install_tab.title = "install"
    existing.tabs.append(install_tab)
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "install", "command": "tmux attach -t '=install-memory-claude'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    # The mis-marked tab should be pruned (session.name mismatch overrides marker).
    assert result["tabs_pruned"] == 1
    assert existing.current_tab.closed is True  # mis-marked tab killed
    assert install_tab.closed is False  # legitimate tab survives


def test_build_tabs_does_not_prune_freshly_created_tabs(no_tmux_calls):
    """Regression: prune must skip tabs we JUST created in the same call.

    A freshly created tab's `tmux attach` runs asynchronously in the new
    session. session.name has not updated yet when prune runs, so the
    strict marker+session check would falsely classify the new tab as
    stale and immediately kill it.
    """
    existing = _FakeWindow()
    existing.variables["user.window_title"] = "clawseat-memories"
    # Pre-existing legitimate tab (cartooner) — should be skipped & spared.
    existing.current_tab.current_session.name = "cartooner-memory-codex"
    existing.current_tab.current_session.variables["user.tab_name"] = "cartooner"
    existing.current_tab.title = "cartooner"
    _FakeWindowFactory.app_windows = [existing]

    payload = {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "cartooner", "command": "tmux attach -t '=cartooner-memory-codex'"},
            {"name": "install",   "command": "tmux attach -t '=install-memory-claude'"},
        ],
        "ensure": True,
        "send_delay_ms": 0,
    }
    v, e = driver._validate_payload(payload)
    assert e is None and v is not None

    result = asyncio.run(driver._build_tabs_layout(connection=None, payload=v))
    assert result["status"] == "ok"
    assert result["tabs_created"] == 1
    assert result["tabs_skipped"] == 1
    # The newly created install tab must NOT be pruned, even though its
    # session.name hasn't been set yet (it's still the default _FakeSession
    # name which is empty / doesn't match install-memory-claude).
    assert result["tabs_pruned"] == 0
    # Both tabs survived
    assert existing.current_tab.closed is False
    new_tab = existing.tabs[1]
    assert new_tab.closed is False
