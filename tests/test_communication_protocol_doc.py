from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "core" / "skills" / "gstack-harness" / "references" / "communication-protocol.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_communication_protocol_has_intent_enum() -> None:
    text = _text()

    for intent in (
        "brief-handoff",
        "dispatch",
        "delivery",
        "verdict-request",
        "verdict",
        "consumed",
        "patrol-finding",
        "escalation",
    ):
        assert intent in text


def test_communication_protocol_has_push_pull() -> None:
    text = _text()

    assert "Push 主路径" in text
    assert "notify_on_done" in text
    assert "send-and-verify.sh" in text
    assert "Pull 兜底" in text
    assert "agent_admin task list-pending --owner-role <r>" in text
