from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "core" / "references" / "collaboration-rules.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_collaboration_rules_routes_browser_qa_to_reviewer() -> None:
    text = _text()
    assert "requires_qa_browser_testing" in text
    assert "requires_multimodal_ui_verification" in text
    assert 'if step.requires_qa_browser_testing or step.requires_multimodal_ui_verification' in text


def test_collaboration_rules_enforces_reviewer_routing_for_qa() -> None:
    text = _text()
    assert (
        "Planner must route browser QA testing steps to reviewer, not builder or patrol."
        in text
    )
