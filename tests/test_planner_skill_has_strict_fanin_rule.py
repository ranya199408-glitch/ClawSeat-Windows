from __future__ import annotations

from pathlib import Path


def test_planner_skill_has_strict_fanin_consumed_rule() -> None:
    text = Path("core/skills/planner/SKILL.md").read_text(encoding="utf-8")

    assert "Strict Fan-in" in text
    assert ".consumed" in text
    assert "BLOCKED" in text
    assert "OO step 1" in text
    assert "planner self-loop" in text
    assert "Inline" in text
    assert "does NOT substitute" in text
