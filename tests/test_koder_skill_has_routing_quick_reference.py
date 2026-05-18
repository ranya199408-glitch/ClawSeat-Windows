import re
from pathlib import Path


def test_koder_skill_has_routing_quick_reference() -> None:
    text = Path("core/skills/clawseat-koder/SKILL.md").read_text(encoding="utf-8")
    assert "Routing Quick Reference" in text
    assert "known project name" in text
    assert "~/.agents/projects/*" in text
    assert "machine.toml" in text
    assert "Koder handles with its own OpenClaw skills" in text
    assert "ClawSeat" in text and "走 chain" in text and "查 memory KB" in text and "派工" in text
    anti_patterns = re.search(r"## 11\. Anti-Patterns(?P<body>.*?)(?:\n## |\Z)", text, re.S)
    assert anti_patterns is not None
    body = anti_patterns.group("body")
    assert "project-related business questions" in body
    assert "answering business questions directly instead of routing to Memory" not in body
