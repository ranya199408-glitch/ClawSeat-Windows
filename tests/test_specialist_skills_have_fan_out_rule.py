from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]

_SPECIALIST_SKILLS = [
    "builder",
    "designer",
    "patrol",
    "reviewer",
]


def _skill_text(skill: str) -> str:
    return (_REPO / "core" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")


def test_specialist_skills_document_disjoint_fan_out_rule() -> None:
    for skill in _SPECIALIST_SKILLS:
        text = _skill_text(skill)
        assert "fan-out" in text, skill
        assert "disjoint" in text, skill
        assert "seat-ownership.md" in text, skill
