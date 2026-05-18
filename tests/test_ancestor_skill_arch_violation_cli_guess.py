from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_skill_flags_cli_guess_and_legacy_api_as_arch_violation() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "### 9.1 Canonical 操作守则（R13 meta-rule）" in text
    assert "凭训练数据拼 CLI" in text
    assert "sudo" in text
    assert "pip install" in text
    assert "brew install" in text
    assert "试旧版 API" in text
    assert "start-identity" in text
    assert "clawseat init" in text
    assert "clawseat-cli" in text
    assert "| \"我猜命令名是 ...\" / 凭训练数据拼 CLI | 必须先查 Common Operations Cookbook / SKILL.md |" in text
    assert "| \"我先 sudo / pip install / brew install ...\" | 禁止改宿主环境 |" in text
    assert "| \"试旧版 API（start-identity / clawseat init / clawseat-cli ...）\" | 这些是 v0.5/v0.6/v0.8 名字，不是 canonical |" in text
