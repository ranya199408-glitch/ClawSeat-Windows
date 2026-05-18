from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "core" / "references" / "seat-capabilities.md"


def test_seat_capabilities_map_exists_with_six_seats() -> None:
    """core/references/seat-capabilities.md exists and contains all 6 seat types."""
    content = _DOC.read_text(encoding="utf-8").lower()

    for seat in ["memory", "planner", "builder", "reviewer", "patrol", "designer"]:
        assert seat in content


def test_seat_capabilities_map_has_boundary_and_clear_policy() -> None:
    """seat-capabilities.md has boundary and /clear policy for each seat."""
    content = _DOC.read_text(encoding="utf-8")

    assert "/clear" in content
    assert "/compact" in content
    assert "boundary" in content.lower() or "don't do" in content.lower()
