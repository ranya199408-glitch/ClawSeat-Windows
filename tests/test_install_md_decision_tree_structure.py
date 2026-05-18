from __future__ import annotations

import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
EN = REPO / "docs" / "INSTALL.md"
ZH = REPO / "docs" / "INSTALL.zh-CN.md"


def _step_section(text: str, heading: str) -> str:
    match = re.search(rf"^### {re.escape(heading)}.*?(?=^### |\Z)", text, re.M | re.S)
    assert match is not None, f"missing step heading: {heading}"
    return match.group(0)


def test_install_md_decision_tree_steps_have_required_schema() -> None:
    """Each EN decision step contains WHAT/WHY/CONFIRM/ON-FAIL."""
    text = EN.read_text(encoding="utf-8")
    for step in range(4):
        section = _step_section(text, f"Step {step}")
        why_marker = "**WHY**" if step == 1 else "**WHY default**"
        for marker in ("**WHAT**", why_marker, "**CONFIRM**", "**ON-FAIL**"):
            assert marker in section, f"{marker} missing in Step {step}"


def test_install_zh_cn_step_count_matches_english() -> None:
    """Chinese install guide stays structurally parallel to the English tree."""
    en_text = EN.read_text(encoding="utf-8")
    zh_text = ZH.read_text(encoding="utf-8")
    en_steps = re.findall(r"^### Step [0-3]\b", en_text, re.M)
    zh_steps = re.findall(r"^### 步骤 [0-3]\b", zh_text, re.M)
    assert len(en_steps) == 4
    assert len(zh_steps) == len(en_steps)
    assert "可以开始吗? [回车=继续 / 详 / 取消]" in zh_text


def test_install_decision_tree_lists_eleven_emoji_progress_steps() -> None:
    """The run phase documents the required 11-step emoji narration."""
    text = EN.read_text(encoding="utf-8")
    section = _step_section(text, "Step 3")
    progress = re.findall(r"^\d+\. [🟢⚠️❌⏭️]", section, re.M)
    assert len(progress) == 11
    for marker in ("🟢", "⚠️", "❌", "⏭️"):
        assert marker in section
