from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_template_has_common_operations_cookbook() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "Common Operations Cookbook" in text
    assert "Seat 生命周期" in text
    assert "Sandbox HOME / lark-cli" in text
    assert "Window / iTerm" in text
    assert "Brief drift" in text
    assert "通讯" in text
    assert "飞书" in text
    assert "agent_admin.py session start-engineer <seat> --project ${PROJECT_NAME}" in text
    assert "agent_admin.py session switch-harness --project ${PROJECT_NAME}" in text
    assert "agent_admin.py session reseed-sandbox --project ${PROJECT_NAME} --all" in text
    assert "agent_admin.py window open-grid --project ${PROJECT_NAME} --recover" in text
    assert "bash ${CLAWSEAT_ROOT}/scripts/memory-brief-mtime-check.sh" in text
    assert "send-and-verify.sh --project ${PROJECT_NAME} <seat>" in text
    assert "send_delegation_report.py" in text
