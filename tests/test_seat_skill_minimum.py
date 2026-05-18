from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILLS = {
    "clawseat-memory": _REPO / "core" / "skills" / "clawseat-memory" / "SKILL.md",
    "planner": _REPO / "core" / "skills" / "planner" / "SKILL.md",
    "builder": _REPO / "core" / "skills" / "builder" / "SKILL.md",
    "reviewer": _REPO / "core" / "skills" / "reviewer" / "SKILL.md",
    "patrol": _REPO / "core" / "skills" / "patrol" / "SKILL.md",
    "designer": _REPO / "core" / "skills" / "designer" / "SKILL.md",
}
_SPECIALIST_LIMIT = 60
_PLANNER_LIMIT = 200


def test_specialist_skills_under_60_lines() -> None:
    for name, path in _SKILLS.items():
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        limit = _PLANNER_LIMIT if name == "planner" else _SPECIALIST_LIMIT
        assert line_count <= limit, f"{name} has {line_count} lines, limit {limit}"
        assert not re.search(r"Phase \d|Phase [A-Z]", path.read_text(encoding="utf-8"))


def test_skills_contain_workflow_collaboration_section() -> None:
    for name, path in _SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert "## Workflow Collaboration" in text
        assert "## Context Management" in text
        # Sections now use shared reference links instead of inline copies
        assert "workflow-collaboration-protocol.md" in text or "workflow-collaboration-template.md" in text
        assert "context-management-protocol.md" in text or "context-management-template.md" in text
        if name == "planner":
            assert "## Workflow Authoring" in text
            assert "COMPACT" in text
            assert "FORBIDDEN" in text
