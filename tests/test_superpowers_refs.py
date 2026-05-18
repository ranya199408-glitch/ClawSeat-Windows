from __future__ import annotations

from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_BORROWED = _REPO / "core" / "references" / "superpowers-borrowed"

_SKILLS = (
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "test-driven-development",
    "systematic-debugging",
    "verification-before-completion",
    "requesting-code-review",
    "receiving-code-review",
    "finishing-a-development-branch",
    "subagent-driven-development",
)

_SEATS = (
    "memory-oracle",
    "planner",
    "builder",
    "reviewer",
    "patrol",
    "designer",
)


def test_attribution_file_exists() -> None:
    text = (_BORROWED / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "https://github.com/obra/superpowers" in text
    assert "Source commit: " in text


@pytest.mark.parametrize("skill", _SKILLS)
def test_all_borrowed_skills_present(skill: str) -> None:
    path = _BORROWED / f"{skill}.md"
    assert path.is_file(), skill
    assert path.read_text(encoding="utf-8").strip(), skill


@pytest.mark.parametrize("seat", _SEATS)
def test_seat_skills_reference_borrowed(seat: str) -> None:
    path = _REPO / "core" / "skills" / seat / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert "## Borrowed Practices" in text, seat
    assert "see [`core/references/superpowers-borrowed/" in text, seat
