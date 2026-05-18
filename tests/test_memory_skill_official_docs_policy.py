from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_memory_skill_requires_official_docs_kb_for_external_integrations() -> None:
    text = (_REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md").read_text(encoding="utf-8")

    assert "Official Documentation Gate" in text
    assert "~/.agents/memory/projects/<project>/findings/" in text
    assert "Package name + version + CLI binary path" in text
    assert "Inference boundary" in text
