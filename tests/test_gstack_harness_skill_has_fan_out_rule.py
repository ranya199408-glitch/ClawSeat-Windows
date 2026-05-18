from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "core" / "skills" / "gstack-harness" / "SKILL.md"
FAN_OUT = REPO / "core" / "skills" / "gstack-harness" / "references" / "sub-agent-fan-out.md"
PLAYBOOK = REPO / "core" / "skills" / "gstack-harness" / "references" / "dispatch-playbook.md"


def test_skill_md_has_fan_out_design_rule() -> None:
    skill_text = SKILL.read_text(encoding="utf-8")
    assert "Sub-agent fan-out is the default" in skill_text, (
        "SKILL.md must contain the canonical Design-rule sentence so every seat loading this skill sees it"
    )
    assert "seat-ownership.md" in skill_text, (
        "SKILL.md must surface the seat-ownership cross-link for the harness ownership boundary"
    )


def test_fan_out_reference_has_trigger_rules() -> None:
    assert FAN_OUT.exists()
    text = FAN_OUT.read_text(encoding="utf-8")

    assert "## When to fan out" in text
    # All 4 canonical trigger rules must be named explicitly — not only a heading
    for marker in (
        "Disjoint file sets",
        "Disjoint test targets",
        "Disjoint research queries",
        "Explicitly named multi-part task",
    ):
        assert marker in text, f"trigger rule '{marker}' missing from fan-out reference"

    # Trigger is an OR (any one) not an AND (all of)
    assert "required** if any of the following are true" in text, (
        "trigger rule must use 'any of the following' (OR semantics) — not 'all of'"
    )


def test_fan_out_reference_has_pattern_and_anti_patterns() -> None:
    text = FAN_OUT.read_text(encoding="utf-8")
    assert "## Fan-out pattern" in text
    assert "## Anti-patterns" in text
    # At least two concrete anti-pattern phrases must appear — the section must
    # carry real content, not just the heading
    concrete_phrases = [
        "I'll do Part A first, then Part B",
        "Fan-out without cross-check",
        "Splitting a single bug fix into fake parallel lanes",
        "Delegating judgment to sub-agents",
    ]
    hits = sum(1 for p in concrete_phrases if p in text)
    assert hits >= 2, (
        f"anti-patterns section must enumerate concrete mistakes (found {hits}/4 canonical phrases)"
    )


def test_fan_out_checklist_matches_trigger_semantics() -> None:
    """
    Regression guard: the receiving-seat checklist must NOT soften the rule
    into 'you need two yes'. Top of the doc says any-one trigger makes fan-out
    required; checklist must mirror that, not contradict it.
    """
    text = FAN_OUT.read_text(encoding="utf-8")
    assert "## Checklist for the receiving seat" in text

    # The broken prior phrasing was 'If any two of those are "yes"'. This must not resurface.
    assert 'any two of those are "yes"' not in text, (
        "checklist must not use 'any two yes' — it contradicts the any-one trigger rule at the top"
    )
    # Positive assertion of the canonical phrasing
    assert "any ONE is" in text or "any one is" in text.lower(), (
        "checklist must use 'any ONE is yes' to mirror the trigger rule"
    )


def test_fan_out_reference_has_worked_examples() -> None:
    text = FAN_OUT.read_text(encoding="utf-8")
    assert "## Example" in text, "worked example section missing"
    # The round-3a style example must be preserved (parallel A/B split of independent file sets)
    assert "parallel:" in text or "agent_A" in text, (
        "worked example demonstrating parallel fan-out pattern missing"
    )


def test_dispatch_playbook_has_fan_out_hint_section() -> None:
    text = PLAYBOOK.read_text(encoding="utf-8")
    assert "## Fan-out hint for multi-part tasks" in text
    # Must include the canonical template objective line for planners to paste
    assert "This task has" in text and "independent sub-parts" in text, (
        "playbook must carry the canonical template line 'This task has N independent sub-parts ...' — "
        "deleting it would break the planner-side contract with specialist seats"
    )
