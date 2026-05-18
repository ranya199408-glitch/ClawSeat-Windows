from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "core/skills/builder/SKILL.md",
    ROOT / "core/skills/planner/SKILL.md",
    ROOT / "core/skills/memory-oracle/SKILL.md",
    ROOT / "core/skills/reviewer/SKILL.md",
    ROOT / "core/skills/designer/SKILL.md",
    ROOT / "core/skills/patrol/SKILL.md",
    ROOT / "core/skills/gstack-harness/SKILL.md",
    ROOT / "core/skills/workflow-architect/SKILL.md",
    ROOT / "core/scripts/agent_admin_workspace.py",
    ROOT / "core/skills/gstack-harness/references/dispatch-playbook.md",
    ROOT / "core/skills/workflow-architect/references/workflow-spec-schema.md",
]

LINK_RE = re.compile(
    r"\[[^\]]+\]\((?P<link>[^)\n]+references/[^)\n]+\.md(?:#[^)]+)?)\)|"
    r"`(?P<code>[^\n`]*references/[^\n`]+\.md[^\n`]*)`"
)


def _resolve_target(source: Path, target: str) -> Path:
    target = target.split("#", 1)[0]
    if target.startswith("core/"):
        return (ROOT / target).resolve()
    return (source.parent / target).resolve()


def test_no_dead_refs_in_skills() -> None:
    dead_refs: list[str] = []
    for path in TARGETS:
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group("link") or match.group("code")
            if not target:
                continue
            resolved = _resolve_target(path, target)
            if not resolved.exists():
                dead_refs.append(f"{path.relative_to(ROOT)} -> {target}")

    assert not dead_refs, "dead refs:\n" + "\n".join(dead_refs)
