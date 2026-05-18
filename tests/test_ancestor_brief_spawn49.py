from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_spawn49_brief_uses_agent_admin_session_start_engineer() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "scripts/wait-for-seat.sh" in text
    assert "~/" not in text
    assert "${AGENT_HOME}/.agents/memory/machine/" in text
    assert "### B2.5 — Bootstrap machine tenants + project-memory 快速概览" in text
    assert "### B2.6" not in text
    assert "tmux send-keys -t '=machine-memory-claude' \"$MEMORY_PROMPT\" Enter" not in text
    assert "${AGENT_HOME}/.agents/memory/learnings/${PROJECT_NAME}-bootstrap-report.md" not in text
    assert "MEMORY_REPORT_READY" not in text
    assert "### B5 — Feishu channel + koder overlay bind（5 子步）" in text
    assert "agent_admin.py project binding-list" in text
    assert "${AGENT_HOME}/.agents/projects/*/project.toml" in text
    assert "project-local.toml" in text
    assert "${AGENT_HOME}/.lark-cli/config.json" in text
    assert "apply-koder-overlay.sh" in text
    assert "lark-cli auth status --as user" in text
    assert "lark-cli im +chat-search" in text
    assert "agent_admin.py project bind" in text
    assert "--feishu-sender-app-id <cli_xxx>" in text
    assert "--feishu-sender-mode <user|bot|auto>" in text
    assert "--openclaw-koder-agent <selected_agent_name>" in text
    assert "send_delegation_report.py" in text
    assert "--as <user|bot|auto>" in text
    assert "--require-mention" in text
    assert "${AGENT_HOME}/.agents/memory/learnings/${PROJECT_NAME}-phase-a-decisions.md" in text
    assert "不要 tmux send-keys 给 memory" in text
    assert "${AGENT_HOME}/.openclaw/workspace.toml" in text
    assert "agent_admin.py session start-engineer ${seat} --project ${PROJECT_NAME}" in text
    assert "agent_admin.py session switch-harness --project ${PROJECT_NAME} --engineer ${seat}" in text
    assert "agent_admin.py session-name ${seat} --project ${PROJECT_NAME}" in text
    assert "window reseed-pane <seat> --project ${PROJECT_NAME}" in text
    assert "claude code oauth" in text
    assert "codex xcode-best api" in text
    assert "gemini cli oauth" in text
    assert "agent_admin window open-grid ${PROJECT_NAME} [--recover]" in text
    assert "--open-memory" not in text
    assert "agent-launcher.sh --headless --engineer ${seat} --project ${PROJECT_NAME}" not in text


def test_brief_uses_v2_memory_vocab_and_project_toml_ssot() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    for stale in ("始祖 CC", "六宫格", "machine-memory-claude", "clawseat-ancestor/SKILL"):
        assert stale not in text
    assert "project.toml SSOT authority" in text
    assert "seat_overrides" in text
    assert "Decisions match overrides: yes/no" in text
    assert "clawseat-memory/SKILL.md" in text
