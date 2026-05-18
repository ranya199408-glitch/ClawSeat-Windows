from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_warns_against_repeated_start_engineer_calls() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "每个 seat 只调用一次 `agent_admin session start-engineer`" in text
    assert "不要反复 `start-engineer` 触发 retry" in text
    assert "agent_admin session status" in text
    assert "tmux has-session" in text
