from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_ANCESTOR_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_table_marks_memory_query_steps() -> None:
    text = _ANCESTOR_SKILL.read_text(encoding="utf-8")

    assert "| Token | memory_query |" in text
    assert "| `B0-memory-query` | yes |" in text
    assert "| `B2.5-bootstrap-tenants` | yes |" in text
    assert "| `B3.5-clarify-providers` | yes |" in text
    assert "| `B1-read-brief` | no |" in text
