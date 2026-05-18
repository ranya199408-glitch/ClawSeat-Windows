from __future__ import annotations

import re
from pathlib import Path


def test_memory_skill_documents_canonical_workflow_entry() -> None:
    text = Path("core/skills/memory-oracle/SKILL.md").read_text(encoding="utf-8")

    assert "Canonical Workflow Entry" in text
    assert "agent_admin.py task create" in text
    assert "workflow.md ready" in text
    assert "notify_on_done: [memory]" in text
    assert "禁止短路" in text

    section = text.split("## Canonical Workflow Entry", 1)[1].split("## Post-Spawn Chain Rehearsal", 1)[0]
    assert re.search(r"1\.\s+Create workflow\.md", section)
    assert re.search(r"2\.\s+Edit workflow\.md", section)
    assert re.search(r"3\.\s+Then wake planner", section)
