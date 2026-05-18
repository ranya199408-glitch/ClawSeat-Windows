from __future__ import annotations

from pathlib import Path


SPECIALIST_SKILLS = (
    Path("core/skills/builder/SKILL.md"),
    Path("core/skills/designer/SKILL.md"),
    Path("core/skills/reviewer/SKILL.md"),
)


def test_specialist_skills_document_todo_queue_priority() -> None:
    for skill_path in SPECIALIST_SKILLS:
        text = skill_path.read_text(encoding="utf-8")
        assert "TODO Queue Priority" in text
        assert "queue head" in text or "先看队首" in text
        assert "superseded" in text
        assert "zombie" in text
