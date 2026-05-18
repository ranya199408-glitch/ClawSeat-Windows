from pathlib import Path


SKILL = Path("core/skills/clawseat-intake/SKILL.md")


def test_socratic_skill_documents_memory_notification_protocol() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "接收 memory 通知协议" in text
    assert "[Memory]" in text
    assert r"^\[Memory\]" in text
    assert "_via Memory @" in text
    assert "task_id={id}" in text
    assert "verdict={PASS|FAIL|BLOCKED}" in text
    assert "Parse footer" in text
