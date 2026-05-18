from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_documents_seat_tui_lifecycle() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "Seat TUI 生命周期（强制理解）" in text
    assert re.search(r"wait-for-seat\.sh.*自动.*re-attach|seat 重启.*自动", text, re.S)
    assert re.search(r"不要手动.*tmux attach|禁止.*tmux attach", text, re.S)
    assert re.search(r"open-grid.*--recover", text, re.S)
