from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_documents_seat_tui_lifecycle() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "Seat TUI 生命周期（强制理解）" in text
    assert re.search(r"wait-for-seat\.sh.*自动.*re-attach|seat 重启.*自动", text, re.S)
    assert re.search(r"不要手动.*tmux attach|禁止.*tmux attach", text, re.S)
    assert re.search(r"open-grid.*--recover", text, re.S)
