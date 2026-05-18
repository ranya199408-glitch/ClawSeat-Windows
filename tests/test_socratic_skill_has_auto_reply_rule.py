from pathlib import Path


def test_socratic_skill_documents_auto_reply_gates() -> None:
    text = Path("core/skills/clawseat-intake/SKILL.md").read_text(encoding="utf-8")
    assert "Auto-reply 判断规则" in text
    assert "verdict=PASS" in text
    assert "verdict=BLOCKED|FAIL" in text
    assert "privacy guard PASS" in text
    assert "task_id 已知" in text
    assert "allowed_groups" in text
    assert "chat_id 不在白名单" in text
