from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_brief_has_five_b5_substeps() -> None:
    text = _BRIEF.read_text(encoding="utf-8")

    assert "### B5 — Feishu channel + koder overlay bind（5 子步）" in text
    assert "#### B5.1 — 选 openclaw agent 做 koder overlay" in text
    assert "#### B5.2 — 飞书 auth pre-flight（按 §5.y 决策树）" in text
    assert "#### B5.3 — 选 sender + 拉群 + 获取 chat_id" in text
    assert "#### B5.4 — operator 粘贴 chat_id → project-memory bind（4 字段）" in text
    assert "#### B5.5 — verify smoke dispatch" in text


def test_brief_b5_uses_v2_bind_fields_and_canonical_smoke_command() -> None:
    text = _BRIEF.read_text(encoding="utf-8")

    assert "--feishu-sender-app-id <cli_xxx>" in text
    assert "--feishu-sender-mode <user|bot|auto>" in text
    assert "--openclaw-koder-agent <selected_agent_name>" in text
    assert "lark-cli im +chat-search --params" in text
    assert "send_delegation_report.py" in text
    assert "--as <user|bot|auto>" in text
