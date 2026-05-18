from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_brief_points_to_skill_section_11() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "## 面对 operator 错误指引" in text
    assert "SKILL.md §11" in text
    assert "red-flag" in text


def test_ancestor_skill_has_red_flag_table_and_override_flow() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "## 11. 识别 operator 错误指引 + 拒绝模板" in text
    assert "ARCH_VIOLATION:" in text
    assert "直接调 launcher，不走 agent_admin" in text
    assert "tmux send-keys 给 memory" in text
    assert "operator-override" in text
    assert "planner stop-hook" in text
