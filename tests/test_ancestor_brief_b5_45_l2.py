from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_includes_feishu_layer2_confirmation_step() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "B5.4.5" in text
    assert "飞书 Layer 2 UI 配置" in text
    assert "https://open.feishu.cn/app" in text
    assert "B5.5" in text
    assert "未确认 → 暂停 B5.5" in text
