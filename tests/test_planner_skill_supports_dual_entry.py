from __future__ import annotations

import re
from pathlib import Path


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    tail = text[start + len(heading):]
    match = re.search(r"\n## ", tail)
    return tail[: match.start()] if match else tail


def test_planner_skill_supports_dual_entry_without_operator_intake_ban() -> None:
    text = Path("core/skills/planner/SKILL.md").read_text(encoding="utf-8")
    boundary = _section(text, "## Boundary")

    assert "Don't: operator intake" not in boundary
    assert "operator intake" not in boundary.split("Don't:", 1)[-1]
    assert "## Dual Entry" in text
    assert "双入口" in text
    assert "Both routes" in text
    assert "memory remains the KB retention authority" in text
