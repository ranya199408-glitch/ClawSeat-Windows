from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_memory_skill_documents_dispatch_protocol_and_absent_planner_fallback() -> None:
    text = (_REPO / "core" / "skills" / "memory-oracle" / "SKILL.md").read_text(encoding="utf-8")
    lowered = text.lower()

    assert "dispatch protocol" in lowered
    assert "dispatch_task.py" in text
    assert "send-and-verify" in text
    assert "absent-planner" in lowered
    assert "profile-dynamic.toml" in text
    assert "Verify Ack" in text
    assert "--profile" in text
    assert "--target-role" in text

    match = re.search(r"Verify Ack 4-step after dispatch:(.*?)(?:\n## |\Z)", text, flags=re.S)
    assert match is not None
    assert len(re.findall(r"^\d+\.", match.group(1), flags=re.M)) >= 4
