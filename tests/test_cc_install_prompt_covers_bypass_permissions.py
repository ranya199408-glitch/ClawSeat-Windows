from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_claude_code_prompt_covers_bypass_permissions() -> None:
    text = (REPO / "docs" / "agents" / "claude-code" / "INSTALL.md").read_text(encoding="utf-8")

    assert "Bypass Permissions" in text
    assert "normal Claude Code authorization" in text
    assert "directly" in text
    assert "Yes, I trust this folder" in text
    assert "Allow this skill to read" in text
    assert "API 401" in text
    assert "absent tmux sessions" in text


def test_generic_install_prompt_covers_startup_trust_auth_prompts() -> None:
    text = (REPO / "docs" / "INSTALL_AGENT_PROMPT.md").read_text(encoding="utf-8")

    assert "Startup Trust/Auth Prompts" in text
    assert "Yes, I trust this folder" in text
    assert "Bypass Permissions" in text
    assert "Allow this skill to read" in text
    assert "browser/OAuth" in text
