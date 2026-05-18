"""Regression: start_engineer auto-refreshes the shared memories iTerm
window when restarting a memory/ancestor seat.

Without this hook, the memories tab still attaches to the OLD (now-killed)
tmux session and the operator sees a stale 'detached' banner.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))


def _make_handler():
    """Construct a SessionLifecycleHandlers with stub hooks just enough to
    invoke the auto-refresh method without touching real subprocess / iterm2.
    """
    from agent_admin_session_lifecycle import SessionStartLifecycle

    hooks = SimpleNamespace(
        load_project=MagicMock(return_value=SimpleNamespace(name="install", template_name="clawseat-creative")),
    )
    handler = SessionStartLifecycle.__new__(SessionStartLifecycle)
    handler.hooks = hooks
    return handler, hooks


def test_refresh_skips_non_memory_seat(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    handler, hooks = _make_handler()
    session = SimpleNamespace(engineer_id="builder", project="install", session="install-builder-codex")
    with patch("agent_admin_window.ensure_memories_pane") as ensure_mock:
        handler._auto_refresh_memories_window_after_memory_start(session)
    ensure_mock.assert_not_called()
    hooks.load_project.assert_not_called()


def test_refresh_skips_when_disabled_via_env(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("CLAWSEAT_DISABLE_MEMORIES_AUTOREFRESH", "1")
    handler, _ = _make_handler()
    session = SimpleNamespace(engineer_id="memory", project="install", session="install-memory-claude")
    with patch("agent_admin_window.ensure_memories_pane") as ensure_mock:
        handler._auto_refresh_memories_window_after_memory_start(session)
    ensure_mock.assert_not_called()


def test_refresh_skips_under_pytest_by_default():
    # PYTEST_CURRENT_TEST is set by pytest itself; the hook should self-suppress.
    handler, _ = _make_handler()
    session = SimpleNamespace(engineer_id="memory", project="install", session="install-memory-claude")
    with patch("agent_admin_window.ensure_memories_pane") as ensure_mock:
        handler._auto_refresh_memories_window_after_memory_start(session)
    ensure_mock.assert_not_called()


def test_refresh_calls_ensure_memories_for_memory_seat(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    handler, hooks = _make_handler()
    session = SimpleNamespace(engineer_id="memory", project="install", session="install-memory-claude")
    with patch("agent_admin_window.ensure_memories_pane") as ensure_mock:
        handler._auto_refresh_memories_window_after_memory_start(session)
    hooks.load_project.assert_called_once_with("install")
    ensure_mock.assert_called_once()


def test_refresh_calls_ensure_memories_for_ancestor_seat(monkeypatch):
    """v1 templates use 'ancestor' as the primary seat id."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    handler, hooks = _make_handler()
    session = SimpleNamespace(engineer_id="ancestor", project="legacy-proj", session="legacy-proj-ancestor")
    with patch("agent_admin_window.ensure_memories_pane") as ensure_mock:
        handler._auto_refresh_memories_window_after_memory_start(session)
    ensure_mock.assert_called_once()


def test_refresh_swallows_load_project_failure(monkeypatch, capsys):
    """Hook must not break start_engineer if load_project raises."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    handler, hooks = _make_handler()
    hooks.load_project.side_effect = RuntimeError("project gone")
    session = SimpleNamespace(engineer_id="memory", project="vanished", session="vanished-memory")
    # Should not raise
    handler._auto_refresh_memories_window_after_memory_start(session)
    captured = capsys.readouterr()
    assert "memories refresh skipped" in captured.err


def test_refresh_swallows_ensure_memories_failure(monkeypatch, capsys):
    """Hook must not break start_engineer if ensure_memories_pane raises."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    handler, _ = _make_handler()
    session = SimpleNamespace(engineer_id="memory", project="install", session="install-memory-claude")
    with patch("agent_admin_window.ensure_memories_pane", side_effect=RuntimeError("iterm down")):
        handler._auto_refresh_memories_window_after_memory_start(session)  # should not raise
    captured = capsys.readouterr()
    assert "ensure_memories_pane" in captured.err
