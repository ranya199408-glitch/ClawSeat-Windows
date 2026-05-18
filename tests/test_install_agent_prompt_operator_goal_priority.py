from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_install_agent_prompts_pin_operator_goal_priority() -> None:
    for relative in ("docs/INSTALL_AGENT_PROMPT.md", "docs/INSTALL_AGENT_PROMPT.zh-CN.md"):
        text = (_REPO / relative).read_text(encoding="utf-8")
        assert "## Operator Goal Priority" in text
        assert "HARD CONSTRAINTS" in text
        assert "operator" in text.lower()
        assert "Step 0" in text
        assert "silently" in text or "静默" in text
