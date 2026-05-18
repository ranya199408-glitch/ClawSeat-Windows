from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_ANCESTOR_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"
_ANCESTOR_PLIST = _REPO / "core" / "templates" / "patrol.plist.in"


def test_ancestor_skill_and_patrol_plist_use_send_and_verify_for_project_seat_messages() -> None:
    skill = _ANCESTOR_SKILL.read_text(encoding="utf-8")
    plist = _ANCESTOR_PLIST.read_text(encoding="utf-8")

    assert "### 5.2 跨 seat 文本通讯（canonical）" in skill
    assert "bash ${CLAWSEAT_ROOT}/core/shell-scripts/send-and-verify.sh" in skill
    assert "你自己 tmux send-keys 给 planner/builder/patrol 发消息" in skill
    # Round-8 #6: `/patrol-tick` was a slash-command-looking token that Claude
    # Code's resolver rejects as "Unknown command". The **active invocation
    # form** must no longer appear — i.e. no `send-and-verify.sh ... ancestor
    # "/patrol-tick"` instruction and no bare `/patrol-tick` payload arg.
    # (Historical explanation text that *mentions* the deprecated token to
    # justify its removal is allowed — we only block live trigger patterns.)
    assert 'ancestor "/patrol-tick"' not in skill
    assert "ancestor '/patrol-tick'" not in plist
    assert 'ancestor "/patrol-tick"' not in plist
    # Round-8 #6: patrol is manual-by-default; LaunchAgent is opt-in via flag.
    assert "--enable-auto-patrol" in skill
    # Round-8 #6: plist payload must be the natural-language Phase-B request
    # that ancestor SKILL §3 recognizes semantically (bilingual).
    assert "Phase-B 稳态巡检" in plist
    assert "Phase-B patrol cycle" in plist
    # Existing canonical-send invariants still hold.
    assert "send-and-verify.sh" in plist
    assert "tmux send-keys -t '={PROJECT}-memory-{TOOL}'" not in plist
    assert "agentctl.sh' session-name memory --project '{PROJECT}'" in plist
    assert "={PROJECT}-ancestor-{TOOL}" not in plist


def test_ancestor_skill_53_uses_project_show_not_broken_engineer_list_flag() -> None:
    """§5.3.2 role-id vs engineer-id diagnostic must use `project show`,
    not `engineer list --project` (which has no --project flag —
    reviewer 526525f nit from iter-11 90dfa12 review)."""
    skill = _ANCESTOR_SKILL.read_text(encoding="utf-8")
    assert "agent_admin.py project show ${PROJECT_NAME}" in skill, (
        "§5.3.2 must use `project show` for per-project engineer discovery"
    )
    # Revert guard: the broken flag form must not reappear.
    assert "engineer list --project" not in skill, (
        "revert detected: `engineer list` has no --project flag "
        "(see core/scripts/agent_admin_parser.py::engineer_list_nested)"
    )


def test_ancestor_skill_53_dispatch_preflight_uses_load_profile_not_raw_toml() -> None:
    """§5.3.6 dispatch roster preflight must call `load_profile().seats`
    to mirror dispatch_task.py's dynamic_roster expansion. Raw
    `data.get("seats", [])` underreports in dynamic_roster projects
    (materialized_seats / legacy_seats / heartbeat owner / discovered
    sessions are merged in by load_profile) — reviewer 526525f nit from
    iter-11 90dfa12 review."""
    skill = _ANCESTOR_SKILL.read_text(encoding="utf-8")
    # Authoritative import + usage must be documented.
    assert "from _common import load_profile" in skill, (
        "§5.3.6 must import gstack-harness loader (mirrors dispatch_task.py)"
    )
    assert "profile_obj.seats" in skill, (
        "§5.3.6 must read seats from load_profile's return value"
    )
    # Explicit callout that raw-TOML seats lie under dynamic_roster.
    assert "dynamic_roster" in skill, (
        "§5.3.6 must explain why raw TOML `data[\"seats\"]` is wrong "
        "under [dynamic_roster] projects"
    )
    # Negative assertion: the broken code pattern must NOT appear as
    # executable code anywhere in the skill. The warning text can
    # reference `data["seats"]` with subscript notation — that's the
    # anti-pattern we're teaching operators to recognize — but any
    # spelling of `data.get("seats", ...)` is the regression-detect
    # signal that someone reintroduced the raw-TOML read path.
    #
    # Whitespace-tolerant regex so formatting variants like
    # `data.get( "seats" , [] )` or `data\n  .get('seats',\n  [])` also
    # trip the guard — reviewer 9c455cc Low nit.
    raw_toml_seats = re.compile(
        r"""data\s*\.\s*get\s*\(\s*["']seats["']\s*,""",
        re.MULTILINE | re.DOTALL,
    )
    match = raw_toml_seats.search(skill)
    assert match is None, (
        "§5.3.6 must not contain executable `data.get(\"seats\", ...)` "
        "(any whitespace/quote variant). That's the pre-iter-11 broken "
        "preflight pattern that underreports seats under "
        f"[dynamic_roster]. Found at offset {match.start() if match else -1}: "
        f"{match.group(0) if match else ''!r}"
    )
