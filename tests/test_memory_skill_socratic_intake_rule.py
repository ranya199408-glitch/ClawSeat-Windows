from __future__ import annotations

from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "SKILL.md"


def test_memory_skill_has_socratic_intake_mandatory_rule() -> None:
    text = SKILL.read_text(encoding="utf-8")
    section_match = text.split("## Skill Loading", 1)
    assert len(section_match) == 2
    section = section_match[1]

    assert "触发条件" in section
    assert "必须用此 skill" in section
    assert "假设执行" in section
    assert "Feishu" in section
    assert "SKILL violation" in section
    assert "for tmux users" not in section

    required_bullets = [
        "触发条件",
        "适用通道",
        "禁止模式",
        "用法",
    ]
    for item in required_bullets:
        assert f"- {item}" in section
