from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "core" / "skills" / "planner" / "references" / "collaboration-rules.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_collaboration_rules_has_status_machine() -> None:
    text = _text()

    assert "pending -> in_progress -> done" in text
    assert "pending -> in_progress -> blocked" in text
    for status in ("pending", "in_progress", "done", "blocked"):
        assert status in text
    assert "atomic sed operations" in text


def test_collaboration_rules_has_watchdog() -> None:
    text = _text()

    assert "对称 watchdog" in text
    assert "If memory is dead, planner restarts memory." in text
    assert "If planner is dead, memory restarts planner." in text
    assert "If both hubs are dead, external `agent-launcher` recovery takes over." in text
