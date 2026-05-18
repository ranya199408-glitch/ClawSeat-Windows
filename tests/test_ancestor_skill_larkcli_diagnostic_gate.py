from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_requires_real_home_gate_before_lark_cli_diagnosis() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "real_user_home()" in text
    assert "shell HOME: $HOME" in text
    assert "session reseed-sandbox --project <name> --all" in text
    assert "未跑这个前置核验就开始下结论" in text
