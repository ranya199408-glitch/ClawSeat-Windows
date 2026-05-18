from __future__ import annotations

import re
from pathlib import Path


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    tail = text[start + len(heading):]
    match = re.search(r"\n## ", tail)
    return tail[: match.start()] if match else tail


def test_memory_skills_allow_privacy_guarded_network_research() -> None:
    for skill_path in (
        Path("core/skills/memory-oracle/SKILL.md"),
        Path("core/skills/clawseat-memory/SKILL.md"),
    ):
        text = skill_path.read_text(encoding="utf-8")
        assert "按需联网" in text
        assert "privacy guard" in text
        assert "core/skills/clawseat-privacy/SKILL.md" in text
        assert "research" in text
        assert "audit" in text
        assert "用户对齐" in text

        if "## 禁止事项" in text:
            forbidden = _section(text, "## 禁止事项")
            assert "不联网" not in forbidden
