from __future__ import annotations

from pathlib import Path


MOVED_DOCS = {
    "communication-protocol.md": Path("core/skills/gstack-harness/references"),
    "collaboration-rules.md": Path("core/skills/planner/references"),
    "memory-operations-policy.md": Path("core/skills/memory-oracle/references"),
    "workflow-doc-schema.md": Path("core/skills/planner/references"),
    "workflow-collaboration-template.md": Path("core/skills/planner/references"),
    "max-iterations-policy.md": Path("core/skills/planner/references"),
    "context-management-template.md": Path("core/skills/clawseat-memory/references"),
    "planner-context-policy.md": Path("core/skills/planner/references"),
}

LEGACY_SYMLINKS = {
    "communication-protocol.md": "../skills/gstack-harness/references/communication-protocol.md",
    "collaboration-rules.md": "../skills/planner/references/collaboration-rules.md",
    "memory-operations-policy.md": "../skills/memory-oracle/references/memory-operations-policy.md",
    "workflow-doc-schema.md": "../skills/planner/references/workflow-doc-schema.md",
    "workflow-collaboration-template.md": "../skills/planner/references/workflow-collaboration-template.md",
    "max-iterations-policy.md": "../skills/planner/references/max-iterations-policy.md",
    "context-management-template.md": "../skills/clawseat-memory/references/context-management-template.md",
    "planner-context-policy.md": "../skills/planner/references/planner-context-policy.md",
}


def test_ref_docs_are_in_skill_folders_with_legacy_symlinks() -> None:
    for doc, expected_dir in MOVED_DOCS.items():
        target = expected_dir / doc
        assert target.exists(), f"Expected {target} to exist after migration"

    for doc, expected_target in LEGACY_SYMLINKS.items():
        legacy = Path("core/references") / doc
        assert legacy.is_symlink(), f"Expected {legacy} to remain a compat symlink"
        assert legacy.readlink().as_posix() == expected_target

    assert Path("core/references/seat-capabilities.md").exists()
    assert Path("core/references/skill-catalog.md").exists()
