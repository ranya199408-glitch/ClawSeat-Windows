from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"
_ANCESTOR_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_brief_template_has_memory_tools_section() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "## memory 交互工具（canonical CLI" in text
    assert "${CLAWSEAT_ROOT}/core/skills/memory-oracle/scripts/query_memory.py" in text
    assert "${CLAWSEAT_ROOT}/core/skills/memory-oracle/scripts/memory_write.py" in text
    assert "--project ${PROJECT_NAME}" in text
    assert "--kind decision" in text
    assert "--content-file /tmp/${PROJECT_NAME}-phase-a-decision.md" in text
    assert "不要把 `tmux send-keys` 用在 memory 上" in text
    assert "tmux send-keys -t '=machine-memory-claude' \"...\"" not in text
    assert "query_memory.py --ask" in text


def test_ancestor_skill_has_memory_cli_examples() -> None:
    text = _ANCESTOR_SKILL.read_text(encoding="utf-8")

    assert "### 5.1 memory 交互工具（直接脚本，不走 tmux）" in text
    assert "${CLAWSEAT_ROOT}/core/skills/memory-oracle/scripts/query_memory.py" in text
    assert "${CLAWSEAT_ROOT}/core/skills/memory-oracle/scripts/memory_write.py" in text
    assert "--search \"feishu\"" in text
    assert "--content-file /tmp/${PROJECT_NAME}-phase-a-decision.md" in text
    assert "不要把 `tmux send-keys` 用在 project memory seat 上" in text
    assert "tmux send-keys -t '=machine-memory-claude' \"...\"" not in text
    assert "query_memory.py --ask" in text
