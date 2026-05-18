from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_documents_feishu_two_layers() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "飞书两层配置（非 @ 响应必需）" in text
    assert "Layer 1" in text
    assert "Layer 2" in text
    assert "只响应 `@` 消息" in text
    assert "完全不响应" in text
    assert "部分群不响应" in text
