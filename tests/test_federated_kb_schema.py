from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_DOC = _REPO / "core" / "references" / "federated-kb-schema.md"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_federated_kb_schema_has_reviewer_findings_path() -> None:
    text = _text()
    assert "reviewer/findings/<ts>-<slug>.md" in text


def test_reviewer_findings_frontmatter_fields() -> None:
    text = _text()
    section = "### reviewer/findings/<ts>-<slug>.md"
    start = text.index(section)
    lines = text[start : start + 600]
    assert "severity: HIGH | MEDIUM | LOW" in lines
    assert "repro: step-by-step repro steps" in lines
    assert "status: open | investigating | resolved" in lines
