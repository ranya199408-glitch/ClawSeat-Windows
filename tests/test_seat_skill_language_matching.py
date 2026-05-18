from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL_PATHS = [
    "core/skills/memory-oracle/SKILL.md",
    "core/skills/planner/SKILL.md",
    "core/skills/builder/SKILL.md",
    "core/skills/patrol/SKILL.md",
    "core/skills/designer/SKILL.md",
    "core/skills/reviewer/SKILL.md",
]


def test_all_seat_skills_have_language_matching_section() -> None:
    for skill_path in _SKILL_PATHS:
        content = (_REPO / skill_path).read_text(encoding="utf-8")
        assert "Operator Language Matching" in content
