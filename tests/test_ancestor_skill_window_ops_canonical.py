from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_canonicalizes_window_ops_through_agent_admin() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "tmux list-panes -t '=${PRIMARY_SESSION_NAME}'" in text
    assert "agent_admin window list-panes --project ${PROJECT_NAME}" not in text
    assert "--open-memory" not in text
    assert "osascript" in text
    assert "iterm_panes_driver.py" in text
