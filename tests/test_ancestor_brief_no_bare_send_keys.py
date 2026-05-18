from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_template_uses_send_and_verify_for_cross_seat_text() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "### 跨 seat 文本通讯（canonical）" in text
    assert "send-and-verify.sh" in text
    assert "tmux send-keys -t ${PROJECT_NAME}-" not in text
