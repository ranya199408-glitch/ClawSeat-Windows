from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "planner" / "SKILL.md"


def test_planner_skill_contains_workflow_authoring_and_liveness() -> None:
    """planner SKILL has workflow authoring, catalog, liveness, dispatch, and swallow refs."""
    content = _SKILL.read_text(encoding="utf-8")

    for keyword in ["skill-catalog", "liveness", "SWALLOW", "assign_owner", "fan-out"]:
        assert keyword.lower() in content.lower(), f"Missing: {keyword}"


def test_planner_skill_compact_only_no_clear() -> None:
    """planner SKILL forbids /clear and only allows /compact."""
    lower = _SKILL.read_text(encoding="utf-8").lower()

    assert "compact" in lower
    assert "forbidden" in lower or "禁止" in lower
