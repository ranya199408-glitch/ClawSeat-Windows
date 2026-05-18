from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"
_SKILL_MD = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_brief_contains_pane_seat_mapping_section() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "Pane ↔ Seat 映射（强制理解）" in text
    assert "user.seat_id" in text
    assert "list-panes" in text
    assert "Row1-Col1 = memory / primary seat" in text
    assert "Row2-Col3 = designer" in text


def test_ancestor_skill_contains_pane_seat_mapping() -> None:
    text = _SKILL_MD.read_text(encoding="utf-8")

    assert "Pane ↔ Seat 映射（不要靠显示名判断）" in text
    assert "user.seat_id" in text
    assert "list-panes" in text
