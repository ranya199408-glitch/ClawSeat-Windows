from __future__ import annotations

from pathlib import Path


SKILL = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_skill_has_three_independent_sections_in_order() -> None:
    text = _text()
    assert "## Operator Language Matching(强制)" in text
    assert text.index("## Compaction Recommendation to Operator(memory↔operator 对话仅)") < text.index(
        "## Technical Term Chinese Annotation(memory↔operator 对话仅)"
    )
    assert text.index("## Technical Term Chinese Annotation(memory↔operator 对话仅)") < text.index(
        "## Reporting Style to Operator(memory↔operator 对话仅)"
    )


def test_skill_sections_all_have_scope_limiter() -> None:
    text = _text()
    assert text.count("memory↔operator 对话仅") >= 3


def test_compaction_section_is_present_and_actionable() -> None:
    text = _text()
    assert "## Compaction Recommendation to Operator(memory↔operator 对话仅)" in text
    assert "建议 /compact — 重要记忆已索引,可安全压缩" in text
    assert "不建议 /compact; 先落盘再说" in text


def test_annotation_section_is_meaning_based() -> None:
    text = _text()
    assert "## Technical Term Chinese Annotation(memory↔operator 对话仅)" in text
    assert "英文术语默认附「中文注释」,注释要讲功能/作用,不要只做字面翻译" in text
    assert "fan-out「分发出去」" in text
    assert "fan-in「汇总回来」" in text
    assert "stop hook「停止时触发的钩子函数」" in text
    assert "坏例: fan-out「扇出」/ fan-in「扇入」/ stop hook「停止钩子」" in text
    assert "注释是 onboarding 工具,不是双语辞典" in text


def test_reporting_section_and_size_guard() -> None:
    text = _text()
    assert "## Reporting Style to Operator(memory↔operator 对话仅)" in text
    assert "AskUserQuestion" in text
    assert "结尾要有下一步" in text
    assert "中英混杂收紧" in text
    assert len(text.splitlines()) < 500
