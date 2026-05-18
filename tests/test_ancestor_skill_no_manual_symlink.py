from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_forbids_manual_lark_cli_symlink_debugging() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "手动 ln -s <sandbox>/.lark-cli" in text
    assert "HOME=<sandbox> lark-cli auth login" in text
    assert "session reseed-sandbox --project <name> --all" in text
