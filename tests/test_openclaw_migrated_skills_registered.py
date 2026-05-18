from __future__ import annotations

import tomllib
from pathlib import Path


OPENCLAW_MIGRATED_SKILLS = [
    "find-skills",
    "agent-reach",
    "cartooner-artisan",
    "cartooner-browser",
    "cartooner-resource-ops",
    "cartooner-video",
    "remotion-delegation",
    "remotion-video-production",
    "storyboard-forge",
    "storyboard-expert",
    "script-analyst",
    "script-writing-expert",
    "viral-copywriter",
    "nano-banana",
    "art-director-expert",
    "pdf",
    "pptx",
    "xlsx",
]


def test_openclaw_skills_in_skill_registry() -> None:
    """core/skill_registry.toml contains all 18 openclaw-migrated skills."""
    data = tomllib.loads(Path("core/skill_registry.toml").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in data["skills"]}

    for skill in OPENCLAW_MIGRATED_SKILLS:
        entry = entries.get(skill)
        assert entry is not None, f"Missing in skill_registry.toml: {skill}"
        assert entry["source"] == "openclaw-migrated"
        assert entry["path"] == f"~/.agents/skills/{skill}/SKILL.md"
        assert entry["required"] is False
        assert entry["roles"] == ["memory"]


def test_openclaw_skills_in_catalog() -> None:
    """skill-catalog.md contains the 18 openclaw-migrated skill names."""
    content = Path("core/references/skill-catalog.md").read_text(encoding="utf-8")
    for skill in OPENCLAW_MIGRATED_SKILLS:
        assert f"| {skill} |" in content, f"Missing in skill-catalog.md: {skill}"
