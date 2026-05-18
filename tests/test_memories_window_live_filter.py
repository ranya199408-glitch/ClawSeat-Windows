"""Regression: build_memories_payload filters out projects whose memory tmux
session is not currently live. Without the filter, dead registry entries
produce -zsh fallback tabs that accumulate across rebuilds.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))

import agent_admin_window  # noqa: E402


def _entry(name: str, tmux_name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, tmux_name=tmux_name)


def test_payload_skips_projects_with_no_live_tmux_session() -> None:
    registry = [
        _entry("install", "install-memory-claude"),
        _entry("cartooner", "cartooner-memory-codex"),
        _entry("dead-project", "dead-project-memory"),  # registered but session killed
        _entry("another-dead", "another-dead-memory"),
    ]
    live = ["install-memory-claude", "cartooner-memory-codex", "unrelated-session"]
    with patch.object(agent_admin_window.projects_registry, "enumerate_projects", return_value=registry), \
         patch.object(agent_admin_window, "_tmux_session_names", return_value=live):
        payload = agent_admin_window.build_memories_payload(SimpleNamespace(name="install"))
    assert payload is not None
    tab_names = [t["name"] for t in payload["tabs"]]
    assert tab_names == ["install", "cartooner"]
    assert "dead-project" not in tab_names
    assert "another-dead" not in tab_names


def test_payload_returns_none_when_registry_has_no_live_sessions() -> None:
    registry = [_entry("dead", "dead-memory")]
    with patch.object(agent_admin_window.projects_registry, "enumerate_projects", return_value=registry), \
         patch.object(agent_admin_window, "_tmux_session_names", return_value=[]):
        payload = agent_admin_window.build_memories_payload(SimpleNamespace(name="anything"))
    assert payload is None


def test_payload_falls_back_to_legacy_memory_session_pattern() -> None:
    # No registry entries, but tmux has bare "<project>-memory" sessions.
    # Used by legacy projects whose registry binding was lost.
    legacy_live = ["foo-memory", "bar-memory", "unrelated-session"]
    with patch.object(agent_admin_window.projects_registry, "enumerate_projects", return_value=[]), \
         patch.object(agent_admin_window, "_tmux_session_names", return_value=legacy_live):
        payload = agent_admin_window.build_memories_payload(SimpleNamespace(name="anything"))
    assert payload is not None
    tab_names = sorted(t["name"] for t in payload["tabs"])
    assert tab_names == ["bar", "foo"]
