from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "reviewer" / "SKILL.md"


def _text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_reviewer_skill_mentions_browser_based_qa_testing() -> None:
    text = _text()
    assert "browser-based UI/QA testing" in text


def test_reviewer_skill_has_qa_mode_and_no_fix_contract() -> None:
    text = _text()
    assert "## QA Testing Mode (browser / multimodal)" in text
    assert "reviewer/findings/<ts>-<slug>.md" in text
    assert "DO NOT fix bugs" in text
    assert "canonical verdict" in text.lower()
    assert "APPROVED" in text
    assert "APPROVED_WITH_NITS" in text
    assert "CHANGES_REQUESTED" in text
    assert "PASS/FAIL" not in text


def test_reviewer_skill_has_visual_review_language() -> None:
    text = _text()
    assert "visual consistency review" in text.lower()
    assert "Replaces designer seat" in text


def test_reviewer_skill_boundary_includes_visual_review() -> None:
    text = _text()
    boundary_start = text.index("## Boundary / Output:")
    after_boundary = text[boundary_start + len("## Boundary / Output:") :]
    next_heading_match = re.search(r"^## ", after_boundary, flags=re.M)
    boundary_section = (
        after_boundary[: next_heading_match.start()]
        if next_heading_match
        else after_boundary
    )
    assert "visual review" in boundary_section.lower()


def test_reviewer_skill_has_visual_review_mode_after_qa() -> None:
    text = _text()
    qa_heading = "## QA Testing Mode (browser / multimodal)"
    vr_heading = "## Visual Review Mode"

    qa_index = text.index(qa_heading)
    vr_index = text.index(vr_heading)
    assert qa_index < vr_index

    vr_start = vr_index + len(vr_heading)
    tail = text[vr_start:]
    next_heading = re.search(r"^## ", tail, flags=re.M)
    vr_section = tail[: next_heading.start()] if next_heading else tail

    step_numbers = [
        int(match.group(1))
        for match in re.finditer(r"^(\d+)\. ", vr_section, flags=re.M)
    ]
    assert step_numbers[:5] == [1, 2, 3, 4, 5]
    assert "/design-review" in vr_section
    assert "/browse" in vr_section
    assert "layout" in vr_section.lower()
    assert "spacing" in vr_section.lower()
    assert "typography" in vr_section.lower()
    assert "color" in vr_section.lower()
    assert "component alignment" in vr_section.lower()
    assert "APPROVED" in vr_section
    assert "APPROVED_WITH_NITS" in vr_section
    assert "CHANGES_REQUESTED" in vr_section
    assert "BLOCKED" in vr_section
    assert "FINDINGS-LOGGED" not in vr_section
    assert "Notify planner" in vr_section


def test_reviewer_skill_retains_diff_review_language() -> None:
    text = _text()
    assert "diff review" in text.lower()
