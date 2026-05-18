from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"


def test_ancestor_brief_template_requires_memory_queries_in_b0_b25_b35() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "B0.0 — memory query（强制）" in text
    assert "harness provider auth network project ${PROJECT_NAME}" in text
    assert "B2.5.0 — memory query（强制）" in text
    assert "bootstrap_machine_tenants machine.toml memory" in text
    assert "B3.5.0 — memory query（强制）" in text
    assert "--project ${PROJECT_NAME}" in text
    assert text.count("query_memory.py") >= 3
