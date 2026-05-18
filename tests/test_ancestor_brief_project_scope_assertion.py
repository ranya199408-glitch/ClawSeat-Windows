from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_requires_project_scope_assertion_before_seat_ops() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert 'echo "scope: project=$PROJECT_NAME memory_session=$memory_session"' in text
    assert "ARCH_VIOLATION: memory 身份错位" in text
    assert "B3.5 / B5 / B6 / B7" in text
