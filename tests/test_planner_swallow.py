from pathlib import Path


def test_planner_swallow_forbids_core_ux_pass_without_bounce_or_escalation() -> None:
    text = Path("core/skills/planner/SKILL.md").read_text(encoding="utf-8")

    assert "SWALLOW PASS DENIED" in text
    assert "core_ux: true" in text
    assert "core_ux_swallow_blocked" in text


def test_planner_strict_fanin_enforces_core_ux_gate() -> None:
    text = Path("core/skills/planner/SKILL.md").read_text(encoding="utf-8")

    assert "core_ux_gate" in text
    assert "BLOCKED" in text
    assert "core_ux=true" in text
