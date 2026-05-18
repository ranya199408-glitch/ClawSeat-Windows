from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
PLANNER = (REPO / "core" / "skills" / "planner" / "SKILL.md").read_text(encoding="utf-8")
MEMORY = (REPO / "core" / "skills" / "memory-oracle" / "SKILL.md").read_text(encoding="utf-8")


def test_planner_skill_keeps_compact_requested_section() -> None:
    assert "## Memory-driven Compaction Request" in PLANNER
    assert "[memory: compact-me]" in PLANNER
    assert "[COMPACT-REQUESTED]" not in PLANNER


def test_planner_skill_no_compaction_hint_fields() -> None:
    assert "compaction_hint" not in PLANNER
    assert "compaction_reason" not in PLANNER


def test_memory_skill_no_planner_context_compaction() -> None:
    assert "## Memory-driven Planner Compaction" in MEMORY
    assert "Planner Context 主动压缩" not in MEMORY
    assert "compaction_hint" not in MEMORY
