from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_builder_skill_delivery_template_has_docs_consulted() -> None:
    text = (_REPO / "core" / "skills" / "builder" / "SKILL.md").read_text(encoding="utf-8")

    assert "Docs Consulted" in text
    assert "N/A — <reason>" in text
    assert "external SDK/API/CLI" in text
