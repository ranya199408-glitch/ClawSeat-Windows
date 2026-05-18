from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_template_has_meta_rule_and_canonical_grep_flow() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "## Meta-rule（最高优先级）" in text
    assert "grep" in text
    assert "CLAWSEAT_MEMORY_BRIEF" in text
    assert "Common Operations Cookbook" in text
    assert "SKILL.md" in text
    assert "Cookbook 没覆盖此场景，请提供命令" in text
    assert "凭训练数据 / 直觉拼装 CLI 命令" in text
    assert "sudo" in text
    assert "pip install" in text
    assert "brew install" in text
