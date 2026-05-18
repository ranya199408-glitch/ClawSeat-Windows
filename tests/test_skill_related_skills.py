from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_batch4_related_skills_present_on_core_seats() -> None:
    for rel in (
        "core/skills/clawseat-memory/SKILL.md",
        "core/skills/planner/SKILL.md",
        "core/skills/builder/SKILL.md",
        "core/skills/designer/SKILL.md",
        "core/skills/clawseat-koder/SKILL.md",
    ):
        text = (_REPO / rel).read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        assert "related_skills:" in frontmatter, rel
        assert "clawseat-decision-escalation" in frontmatter, rel
        assert "clawseat-privacy" in frontmatter, rel
