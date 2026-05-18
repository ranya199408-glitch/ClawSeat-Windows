from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
EN = REPO / "docs" / "agents" / "claude-code" / "INSTALL.md"
ZH = REPO / "docs" / "agents" / "claude-code" / "INSTALL.zh-CN.md"


def test_claude_code_prompt_uses_askuserquestion_after_detect() -> None:
    """Claude Code prompt must prefer rich AskUserQuestion UI for confirmations."""
    en = EN.read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")

    for text in (en, zh):
        assert "2. **Bash**" in text
        assert "3. **AskUserQuestion**" in text
        assert "AskUserQuestion reference JSON" in text
        assert '"question"' in text
        assert '"header"' in text
        assert '"options"' in text
        assert "Bash run_in_background" in text
        assert "TaskCreate" in text

    assert en.index("2. **Bash**") < en.index("3. **AskUserQuestion**") < en.index("4. **Bash run_in_background**")
    assert zh.index("2. **Bash**") < zh.index("3. **AskUserQuestion**") < zh.index("4. **Bash run_in_background**")
