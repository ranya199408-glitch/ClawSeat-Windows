from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"
_BRIEF = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_skill_has_auth_decision_tree() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "### 5.y · Feishu auth 状态决策树" in text
    assert "| user_valid | bot_valid | 正确响应 |" in text
    assert "send_delegation_report.py --as user" in text
    assert "send_delegation_report.py --as bot" in text
    assert "feishu_sender_mode = \"auto\"" in text
    assert "feishu_sender_app_id" in text
    assert "openclaw_koder_agent" in text


def test_brief_b5_references_auth_decision_tree() -> None:
    text = _BRIEF.read_text(encoding="utf-8")

    assert "按 SKILL.md §5.y 里的四种状态决定 sender mode" in text
    assert "lark-cli auth status --as user" in text
    assert "lark-cli auth status --as bot" in text
