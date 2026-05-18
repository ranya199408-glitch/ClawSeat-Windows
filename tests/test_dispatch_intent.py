"""Lock the koder → dispatch_task.py `--intent` mapping.

Background
----------
SOUL.md §5 (the "代用户激活 gstack skill" hard rule) says: when a user
describes a need in natural language ("做个工程审查", "推上去", "想大一点"),
koder is responsible for translating that into a gstack skill activation —
the user should not have to memorise trigger phrases.

The mechanism is `dispatch_task.py --intent <key>`: for each intent key,
the dispatch prepends a canonical trigger phrase to the objective AND
appends the skill's SKILL.md path to `--skill-refs`. The downstream
planner Claude Code runtime then matches the trigger and loads the skill
from the referenced SKILL.md.

This test locks the mapping end-to-end — trigger phrase text, SKILL.md
path, and the idempotence/dedup behaviour.

Why lock the string exactly?
----------------------------
1. Each gstack SKILL.md has a frontmatter-level trigger phrase. If the
   value in INTENT_MAP drifts from the SKILL.md text, planner's runtime
   will stop matching and the skill silently goes un-used.
2. SKILL.md paths are absolute and resolved at dispatch time. If the path
   changes (e.g. gstack reorgs its directory layout), every intent using
   that path breaks — this test catches it on every PR.
3. INTENT_MAP is documented verbatim in TOOLS/dispatch.md. If the two
   drift, koder and the code disagree on what `--intent X` does.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

from dispatch_task import INTENT_MAP, apply_intent  # noqa: E402


# ── Structural invariants on the map ─────────────────────────────────────


def test_all_intents_have_trigger_and_skill_md():
    """Every intent must carry both a trigger phrase and a SKILL.md path.
    A missing trigger makes the intent a no-op; a missing skill_md means
    planner can't read the skill definition.
    """
    for key, spec in INTENT_MAP.items():
        assert spec.get("trigger"), f"intent {key!r} missing 'trigger'"
        assert spec.get("skill_md"), f"intent {key!r} missing 'skill_md'"
        assert spec.get("description"), f"intent {key!r} missing 'description'"


def test_skill_md_paths_point_to_gstack_tree():
    """SKILL.md absolute paths must all live under the gstack skills tree.
    If any entry points elsewhere, someone added a non-gstack skill to a
    map that TOOLS/dispatch.md says is gstack-only — cue for docs review.
    """
    for key, spec in INTENT_MAP.items():
        p = spec["skill_md"]
        # Path must contain the gstack skills directory (dot-prefixed ~/.gstack).
        assert "/.gstack/repos/gstack/.agents/skills/" in p, (
            f"intent {key!r} skill_md {p!r} is NOT under the gstack "
            "skills tree — this is surprising, double-check"
        )
        assert p.endswith("/SKILL.md"), (
            f"intent {key!r} skill_md {p!r} does not end in /SKILL.md"
        )


def test_expected_intent_keys_present():
    """Pin the canonical 17 intents (9 plan + 8 specialist-facing).
    If one disappears, TOOLS/dispatch.md (koder) AND the dispatch playbook
    rendered for planner (agent_admin_workspace.py) need matching updates.

    The 17 intents split into:
    - plan-phase (planner's own skills): eng-review, ceo-review,
      design-review, devex-review
    - build/ship (builder-1): ship, land, investigate, freeze, unfreeze
    - review (reviewer-1): code-review
    - QA (qa-1): qa-test, qa-only
    - design (designer-1): design-critique, design-html, design-shotgun
    - cross-cutting: office-hours, checkpoint
    """
    expected = {
        # plan-phase (planner)
        "eng-review",
        "ceo-review",
        "design-review",
        "devex-review",
        # build / ship (builder-1)
        "ship",
        "land",
        "investigate",
        "freeze",
        "unfreeze",
        # review (reviewer-1)
        "code-review",
        # QA (qa-1)
        "qa-test",
        "qa-only",
        # design (designer-1)
        "design-critique",
        "design-html",
        "design-shotgun",
        # cross-cutting
        "office-hours",
        "checkpoint",
    }
    missing = expected - set(INTENT_MAP.keys())
    extra = set(INTENT_MAP.keys()) - expected
    assert not missing, f"intent(s) missing from map: {sorted(missing)}"
    # Extra is fine — someone may have added a new intent. Just notice it.
    if extra:
        # Not a failure: allow additions. Surface them so test-update PRs
        # can sync this expected set deliberately.
        print(f"note: new intents detected: {sorted(extra)}")


# ── Expansion behaviour ────────────────────────────────────────────────


def test_apply_intent_prepends_trigger_and_appends_skill_md():
    objective = "审查新 webhook handler 的执行计划"
    new_obj, new_refs = apply_intent("eng-review", objective, None)
    # Trigger must be prepended (in bold, prefixed to the user's own wording)
    assert new_obj.startswith("**")
    assert "Review the architecture" in new_obj
    assert objective in new_obj  # user's own wording preserved
    # Skill-ref must be injected
    assert any("gstack-plan-eng-review/SKILL.md" in r for r in new_refs)


def test_apply_intent_is_idempotent_on_trigger():
    """If the canonical trigger phrase is already in the objective verbatim
    (koder hand-wrote it, or re-ran the same dispatch), don't duplicate it.

    The idempotence check is a substring match on the full INTENT_MAP trigger.
    This is deliberately strict — the intent is to catch exact duplicates,
    not to detect semantic overlap. If the operator paraphrases the trigger,
    the second prepend is acceptable because the paraphrase may not actually
    activate the skill on its own.
    """
    trigger = INTENT_MAP["eng-review"]["trigger"]
    objective = f"{trigger} — checking src/webhooks/"
    new_obj, _refs = apply_intent("eng-review", objective, None)
    # Objective already contained the trigger → apply_intent must NOT prepend
    # a second copy.
    assert new_obj == objective, (
        f"expected objective unchanged (trigger already present) but got:\n{new_obj}"
    )


def test_apply_intent_dedupes_skill_ref():
    """If the operator already passed the skill SKILL.md via --skill-refs,
    don't append a duplicate.
    """
    existing = INTENT_MAP["ship"]["skill_md"]
    _new_obj, new_refs = apply_intent("ship", "deploy this thing", [existing])
    assert new_refs.count(existing) == 1


def test_apply_intent_preserves_existing_skill_refs():
    """Existing unrelated skill-refs must be preserved when intent
    adds its own skill_md.
    """
    unrelated = "/some/other/reference.md"
    new_obj, new_refs = apply_intent("ship", "deploy", [unrelated])
    assert unrelated in new_refs
    assert any("gstack-ship/SKILL.md" in r for r in new_refs)


def test_apply_intent_none_is_passthrough():
    """No --intent = no mutation."""
    new_obj, new_refs = apply_intent(None, "raw objective", ["ref-a"])
    assert new_obj == "raw objective"
    assert new_refs == ["ref-a"]
    # None skill_refs should become empty list, not None
    new_obj2, new_refs2 = apply_intent(None, "raw objective", None)
    assert new_refs2 == []


def test_apply_intent_unknown_raises_with_valid_list():
    """Typoed intent keys must fail loudly with the full valid-intent list.

    Catches silent no-op: if we returned inputs unchanged on unknown
    intents, koder would write objectives without the trigger phrase and
    planner would never activate the skill — a silent failure.
    """
    with pytest.raises(ValueError) as excinfo:
        apply_intent("shipit", "deploy", None)
    msg = str(excinfo.value)
    assert "shipit" in msg  # the bad key
    # Valid intents should be listed for the operator
    assert "ship" in msg
    assert "eng-review" in msg


# ── Per-intent end-to-end assertion ────────────────────────────────────


@pytest.mark.parametrize("intent", sorted(INTENT_MAP.keys()))
def test_every_intent_produces_non_empty_effect(intent):
    """Every intent, when applied to an empty-ish objective, must:
    - produce an objective that contains the trigger phrase (non-empty)
    - produce skill_refs containing the expected SKILL.md path
    """
    spec = INTENT_MAP[intent]
    new_obj, new_refs = apply_intent(intent, "placeholder task", None)
    assert spec["trigger"].split(".")[0][:20].lower() in new_obj.lower(), (
        f"intent {intent!r} failed to inject trigger prefix"
    )
    assert spec["skill_md"] in new_refs


# ── Specialist-facing intents: correct SKILL.md routing ──────────────────
#
# Lock each specialist intent to the right gstack skill. If someone renames
# a gstack skill or rewires the intent to the wrong SKILL.md, planner will
# activate the wrong runtime on specialist. Mismatch here = wrong behaviour
# in live task chains.


@pytest.mark.parametrize(
    "intent,expected_skill_basename",
    [
        # Build / ship intents point at builder-1's gstack skills
        ("ship", "gstack-ship"),
        ("land", "gstack-land-and-deploy"),
        ("investigate", "gstack-investigate"),
        ("freeze", "gstack-freeze"),
        ("unfreeze", "gstack-unfreeze"),
        # Review intent points at reviewer-1's skill (gstack-review, NOT
        # gstack-plan-*-review which is planner's own)
        ("code-review", "gstack-review"),
        # QA intents point at qa-1's skills
        ("qa-test", "gstack-qa"),
        ("qa-only", "gstack-qa-only"),
        # Design intents point at designer-1's skills
        ("design-critique", "gstack-design-review"),
        ("design-html", "gstack-design-html"),
        ("design-shotgun", "gstack-design-shotgun"),
    ],
)
def test_specialist_intents_route_to_correct_skill(intent, expected_skill_basename):
    """Each specialist intent must point at the SKILL.md of the named gstack
    skill. If renamed or re-pointed, activation breaks silently in production.
    """
    spec = INTENT_MAP[intent]
    assert f"/{expected_skill_basename}/SKILL.md" in spec["skill_md"], (
        f"intent {intent!r} skill_md {spec['skill_md']!r} does not point at "
        f"/{expected_skill_basename}/SKILL.md"
    )


def test_code_review_and_design_review_are_not_confused():
    """`code-review` is reviewer-1's PR-diff review (gstack-review).
    `design-review` is planner's PLAN-MODE UX review (gstack-plan-design-review).
    `design-critique` is designer-1's POST-implementation visual audit
    (gstack-design-review).

    These three MUST point at three different SKILL.md files. Easy to mix
    up in the head.
    """
    code_review_skill = INTENT_MAP["code-review"]["skill_md"]
    design_review_skill = INTENT_MAP["design-review"]["skill_md"]
    design_critique_skill = INTENT_MAP["design-critique"]["skill_md"]
    assert code_review_skill != design_review_skill
    assert code_review_skill != design_critique_skill
    assert design_review_skill != design_critique_skill
    assert "gstack-review/" in code_review_skill
    assert "gstack-plan-design-review/" in design_review_skill
    assert "gstack-design-review/" in design_critique_skill
    assert "plan-design-review" not in design_critique_skill  # not planner's


def test_qa_test_vs_qa_only_distinct():
    """qa-test actually edits code (test→fix→verify loop); qa-only is
    report-only. If someone collapses these to the same SKILL.md, a
    planner dispatch with `--intent qa-only` might end up fixing bugs
    when the caller explicitly asked for report-only.
    """
    assert INTENT_MAP["qa-test"]["skill_md"] != INTENT_MAP["qa-only"]["skill_md"]
    assert "gstack-qa/" in INTENT_MAP["qa-test"]["skill_md"]
    assert "gstack-qa-only/" in INTENT_MAP["qa-only"]["skill_md"]
