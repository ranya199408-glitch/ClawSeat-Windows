from __future__ import annotations

from pathlib import Path


def test_builder_pty_exhaustion_sends_blocked_not_kill():
    """Builder must escalate PTY exhaustion instead of stopping sessions."""
    skill = Path("core/skills/builder/SKILL.md").read_text(encoding="utf-8")
    lower_skill = skill.lower()

    assert "pty exhaustion" in lower_skill
    assert "[blocked:reason=pty-exhaustion]" in lower_skill
    assert "kill-session" not in lower_skill
    assert "tmux kill" not in lower_skill
    assert len(skill.splitlines()) <= 60

    collab = Path("core/skills/planner/references/collaboration-rules.md").read_text(encoding="utf-8")
    assert "PTY_EXHAUSTION" in collab
    assert "cross-project" in collab.lower()
    assert "memory escalation" in collab.lower()
