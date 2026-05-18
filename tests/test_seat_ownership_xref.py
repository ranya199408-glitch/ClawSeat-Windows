from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEAT_SKILLS = [
    ROOT / "core/skills/builder/SKILL.md",
    ROOT / "core/skills/planner/SKILL.md",
    ROOT / "core/skills/memory-oracle/SKILL.md",
    ROOT / "core/skills/reviewer/SKILL.md",
    ROOT / "core/skills/designer/SKILL.md",
    ROOT / "core/skills/patrol/SKILL.md",
    ROOT / "core/skills/gstack-harness/SKILL.md",
    ROOT / "core/skills/workflow-architect/SKILL.md",
]


def test_each_seat_skill_xrefs_seat_ownership() -> None:
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in SEAT_SKILLS
        if "seat-ownership" not in path.read_text(encoding="utf-8")
    ]

    assert not missing, "missing seat-ownership refs:\n" + "\n".join(missing)
