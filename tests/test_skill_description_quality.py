from __future__ import annotations

import re
from pathlib import Path


SKILL_PATHS = [
    "core/skills/clawseat-memory/SKILL.md",
    "core/skills/planner/SKILL.md",
    "core/skills/builder/SKILL.md",
    "core/skills/reviewer/SKILL.md",
    "core/skills/patrol/SKILL.md",
    "core/skills/designer/SKILL.md",
    "core/skills/clawseat-decision-escalation/SKILL.md",
    "core/skills/clawseat-koder/SKILL.md",
    "core/skills/clawseat-privacy/SKILL.md",
    "core/skills/clawseat-memory-reporting/SKILL.md",
    "core/skills/memory-oracle/SKILL.md",
    "core/skills/clawseat-install/SKILL.md",
    "core/skills/clawseat/SKILL.md",
    "core/skills/cs/SKILL.md",
]


def _get_description(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    frontmatter = re.search(r"\A---\n(?P<body>.*?)\n---", text, re.S)
    assert frontmatter, f"{path}: missing YAML frontmatter"
    body = frontmatter.group("body")

    inline = re.search(r"(?m)^description:\s*(?P<value>.+)$", body)
    if inline and inline.group("value").strip() not in {">", "|"}:
        return inline.group("value").strip().strip("\"'")

    block = re.search(r"(?ms)^description:\s*[>|]\s*\n(?P<value>(?:  .+\n?)+)", body)
    if not block:
        return ""
    return " ".join(line.strip() for line in block.group("value").splitlines()).strip()


def test_skill_descriptions_have_use_when_and_exclusion() -> None:
    for path in SKILL_PATHS:
        desc = _get_description(path)
        assert "use when" in desc.lower(), f"{path}: missing 'Use when'"
        assert "do not use for" in desc.lower(), f"{path}: missing 'Do NOT use for'"


def test_skill_descriptions_meet_length_requirement() -> None:
    for path in SKILL_PATHS:
        desc = _get_description(path)
        words = len(desc.split())
        assert words >= 30, f"{path}: description too short ({words} words, need >=30)"
        assert words <= 200, f"{path}: description too long ({words} words, max 200)"
