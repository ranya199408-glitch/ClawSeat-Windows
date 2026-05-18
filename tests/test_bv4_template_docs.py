from __future__ import annotations

from pathlib import Path

EN_DOC = Path("docs/INSTALL.md")
ZH_DOC = Path("docs/INSTALL.zh-CN.md")
ARCH_DOC = Path("docs/ARCHITECTURE.md")


def _must_contain_template_names(text: str) -> None:
    for template in ("clawseat-engineering", "clawseat-creative", "clawseat-solo"):
        assert f"`{template}`" in text, f"missing template reference: {template}"


def test_install_docs_use_three_template_roster() -> None:
    for path in (EN_DOC, ZH_DOC):
        text = path.read_text(encoding="utf-8")
        _must_contain_template_names(text)
        assert "cartooner-creative" not in text
        assert "team-creation" not in text
        assert "clawseat-minimal" not in text.lower()


def test_install_docs_template_section_has_only_three() -> None:
    en = EN_DOC.read_text(encoding="utf-8")
    zh = ZH_DOC.read_text(encoding="utf-8")

    assert (
        "`clawseat-engineering`: 5-seat engineering template (memory + planner + builder + reviewer + patrol),"
        in en
    )
    assert (
        "`clawseat-creative`: 5-seat cartooner-bound creative team (memory + writer + builder-image + builder-av + patrol)."
        in en
    )
    assert (
        "`clawseat-solo`: 3-seat collaboration template (memory + builder + planner-gemini),"
        in en
    )

    assert "| `clawseat-engineering` | 5 | 工程类：memory + planner + builder + reviewer + patrol，绑 gstack skill |" in zh
    assert "| `clawseat-creative` | 5 | 创意类（绑 cartooner skill）：memory + writer + builder-image + builder-av + patrol |" in zh
    assert "| `clawseat-solo` | 3 | 极简协作，全 OAuth：memory + builder + planner-gemini |" in zh


def test_install_docs_default_recommended_engineering() -> None:
    en = EN_DOC.read_text(encoding="utf-8")
    zh = ZH_DOC.read_text(encoding="utf-8")

    assert "default to `clawseat-engineering`" in en
    assert "默认 `clawseat-engineering`" in zh


def test_architecture_reflects_three_template_rows() -> None:
    arch = ARCH_DOC.read_text(encoding="utf-8")
    assert "`clawseat-engineering` | memory planner builder reviewer patrol | 5 | Engineering chain with reviewer (QA + visual review)" in arch
    assert "`clawseat-creative` | memory writer builder-image builder-av patrol | 5 | Cartooner-bound creative team" in arch
    assert "`clawseat-solo` | memory (claude oauth) + builder (codex oauth) + planner (gemini oauth) | 3 |" in arch
    assert "cartooner-creative" not in arch
    assert "team-creation" not in arch


def test_architecture_has_no_legacy_designer_seat_note() -> None:
    arch = ARCH_DOC.read_text(encoding="utf-8")
    assert "designer` row is intentionally not part of `cartooner-creative`" not in arch
    assert "memory`, `planner`, `builder`, `reviewer`, `patrol" in arch
