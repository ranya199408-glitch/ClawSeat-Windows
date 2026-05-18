from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def test_install_agent_prompts_define_voice_confirmation_and_failure() -> None:
    """Generic and Claude Code install prompts expose the EE voice contract."""
    for relative in (
        "docs/INSTALL_AGENT_PROMPT.md",
        "docs/INSTALL_AGENT_PROMPT.zh-CN.md",
        "docs/agents/claude-code/INSTALL.md",
        "docs/agents/claude-code/INSTALL.zh-CN.md",
    ):
        text = _read(relative)
        assert "Voice & Tone" in text
        assert "Confirmation Pattern" in text
        assert "Failure Pattern" in text
        assert "detect_all" in text
        assert "/en" in text
        assert "/zh" in text
        assert "详" in text


def test_claude_code_prompt_names_required_tools() -> None:
    """Claude Code variant documents Read, Bash, Monitor, and TaskCreate usage."""
    text = _read("docs/agents/claude-code/INSTALL.md")
    for expected in ("Read", "Bash run_in_background", "Monitor", "TaskCreate"):
        assert expected in text


def test_install_decision_tree_uses_recommendation_pattern() -> None:
    """INSTALL.md steps must use the star recommendation pattern."""
    text = _read("docs/INSTALL.md")
    assert "Recommended★" in text
    assert "Reason:" in text
    assert "可以开始吗? [回车=继续 / 详 / 取消]" in text
