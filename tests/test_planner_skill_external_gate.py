from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_planner_skill_contains_dispatch_gate() -> None:
    text = (_REPO / "core" / "skills" / "planner" / "SKILL.md").read_text(encoding="utf-8")

    assert "Official Docs Dispatch Gate" in text
    assert "external SDK/API/CLI" in text
    assert "docs_consulted:<kb-path>" in text
    assert "docs_skip_reason:<why>" in text
