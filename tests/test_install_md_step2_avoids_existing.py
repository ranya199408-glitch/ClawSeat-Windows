from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
EN = REPO / "docs" / "INSTALL.md"
ZH = REPO / "docs" / "INSTALL.zh-CN.md"


def test_install_step2_treats_existing_projects_as_avoid_list() -> None:
    """Step 2 must not recommend existing project names as defaults."""
    en = EN.read_text(encoding="utf-8")
    zh = ZH.read_text(encoding="utf-8")

    for text in (en, zh):
        assert "existing_projects" in text
        assert "AVOID list" in text
        assert "operator goal" in text
        assert "repo" in text
        assert "generated unique name" in text
        assert "timestamp" in text

    assert "operator goal first, repo directory name second, generated unique name with timestamp third" in en
    assert "operator goal > repo 目录名 > 带 timestamp 的 generated unique name" in zh
