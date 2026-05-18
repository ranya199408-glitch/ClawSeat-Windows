"""Pin tests: all Gemini runtime exec paths include -y (--yolo)."""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GEMINI_RUNTIME = _REPO / "core" / "launchers" / "runtimes" / "gemini.sh"


def _launcher_text() -> str:
    return _GEMINI_RUNTIME.read_text(encoding="utf-8")


def test_all_exec_gemini_have_yolo_flag() -> None:
    """Every `exec gemini` line must include -y; no bare `exec gemini` allowed."""
    text = _launcher_text()
    bare = re.findall(r"^\s*exec gemini\s*$", text, re.MULTILINE)
    assert not bare, (
        f"Found {len(bare)} bare 'exec gemini' line(s) without -y flag:\n"
        + "\n".join(bare)
    )


def test_exec_gemini_yolo_count_at_least_three() -> None:
    """All 3 exec paths (oauth, custom-model, fallback) must carry -y."""
    text = _launcher_text()
    yolo_lines = re.findall(r"^\s*exec gemini\s+-y", text, re.MULTILINE)
    assert len(yolo_lines) >= 3, (
        f"Expected ≥3 'exec gemini -y' lines, found {len(yolo_lines)}"
    )


def test_exec_gemini_custom_model_has_yolo() -> None:
    """The custom-model exec path must be `exec gemini -y -m ...`."""
    text = _launcher_text()
    assert "exec gemini -y -m" in text, (
        "exec gemini with custom model must include -y before -m"
    )
