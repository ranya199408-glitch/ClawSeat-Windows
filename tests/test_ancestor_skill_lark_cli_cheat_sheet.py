from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_skill_has_real_lark_cli_cheat_sheet() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "### 5.x · Feishu via lark-cli（canonical 命令）" in text
    assert "lark-cli auth status" in text
    assert "lark-cli auth status --as user" in text
    assert "lark-cli auth status --as bot" in text
    assert "lark-cli im +chat-search" in text
    assert "lark-cli im +messages-send" in text
    assert "send_delegation_report.py" in text
    assert "--as auto" in text
    assert "lark-cli chats list" not in text
    assert "lark-cli app / OpenClaw agent app 不混" in text
    assert "OpenClaw koder overlay 目标" in text
    assert "open-grid --recover" in text
    assert "--recover" in text
    assert "--open-memory" not in text
    assert "feishu_sender_app_id" in text
    assert "openclaw_koder_agent" in text
