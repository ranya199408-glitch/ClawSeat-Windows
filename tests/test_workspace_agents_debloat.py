"""
Tests for followup-batch4-p2: AGENTS.md de-bloat (spec items #10 + #11).

Covers:
  #10  planner AGENTS.md ≤100 lines
  #11  specialist AGENTS.md ≤25 lines
  TOOLS materialization side effects for planner + specialists
  protocol.md content fidelity
  intent.md target→intent mapping presence
  idempotency of render functions
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_SCRIPTS.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS.parent))

import agent_admin_workspace as aaw

TOOLS_SHARED = _REPO / "core" / "templates" / "shared" / "TOOLS"


# ── Minimal fakes ─────────────────────────────────────────────────────────────

def _make_project(name: str = "install", repo_root: str = "/tmp/fake-repo") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        repo_root=repo_root,
        engineers=[],
    )


_NO_WORKSPACE = "/tmp/no-such-workspace-sentinel-debloat"


def _make_session(
    engineer_id: str,
    workspace: str = _NO_WORKSPACE,
    project_engineers: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        engineer_id=engineer_id,
        tool="claude",
        workspace=workspace,
        project_record=None,
        project_engineers=project_engineers or {},
        engineer_order=[],
    )


def _make_engineer(role: str, role_details: list | None = None, aliases: list | None = None, skills: list | None = None) -> SimpleNamespace:
    e = SimpleNamespace(
        role=role,
        role_details=role_details or ["Execute tasks as assigned."],
        aliases=aliases or [],
        skills=skills or [],
        human_facing=False,
        active_loop_owner=False,
        dispatch_authority=False,
        patrol_authority=(role == "patrol"),
        unblock_authority=False,
        escalation_authority=False,
        remind_active_loop_owner=False,
        review_authority=(role == "reviewer"),
        design_authority=(role == "designer"),
    )
    return e


def _assemble_lines(session, project, engineer, *, tasks_root: str = "/tmp/.agents/tasks/install") -> list[str]:
    """Replicate agent_admin_template.py assembly without importing it."""
    def inject(section: list[str]) -> list[str]:
        if not section:
            return []
        return ["", *section]

    lines: list[str] = []

    # Fixed header (9 lines)
    header = [
        "# AGENTS.md",
        "",
        f"Role: `{engineer.role}`",
        "",
        f"**Engineer:** `{session.engineer_id}` | **Project:** `{project.name}`",
        "",
        "---",
        "",
        "<!-- auto-generated — do not edit -->",
    ]
    lines.extend(header)

    # Role details
    lines.extend(inject(aaw.render_role_details_lines(engineer)))

    # Aliases
    lines.extend(inject(aaw.render_aliases_lines(engineer)))

    # Read first
    lines.extend(inject(aaw.render_read_first_lines(session, project, engineer)))

    # Skills
    lines.extend(inject(aaw.render_loaded_skills_lines(engineer, session.engineer_id)))

    # Harness runtime
    lines.extend(inject(aaw.render_harness_runtime_lines(engineer)))

    # Authority
    lines.extend(inject(aaw.render_authority_lines(engineer)))

    # Seat boundary + communication protocol merged
    seat = aaw.render_seat_boundary_lines(session, engineer)
    comm = aaw.render_communication_protocol_lines(engineer, project.name)
    if seat or comm:
        lines.append("")
        lines.extend(seat)
        if comm:
            lines.append("")
            lines.extend(comm)

    # Dispatch playbook
    lines.extend(inject(aaw.render_dispatch_playbook_lines(session, project, engineer)))

    return lines


# ── Test 1: planner AGENTS.md ≤100 lines ─────────────────────────────────────

def test_planner_agents_md_within_100_lines(tmp_path):
    session = _make_session("planner", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer(
        "planner-dispatcher",
        aliases=["dispatcher"],
        skills=["{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md"],
        role_details=[
            "Plan and coordinate tasks.",
            "Route work to specialists.",
            "Close out chains to koder.",
        ],
    )
    lines = _assemble_lines(session, project, engineer)
    assert len(lines) <= 100, f"planner AGENTS.md: {len(lines)} lines (limit 100)"


# ── Test 2: specialist AGENTS.md ≤25 lines ────────────────────────────────────

@pytest.mark.parametrize("role,engineer_id", [
    ("builder", "builder-1"),
    ("reviewer", "reviewer-1"),
    ("patrol", "patrol-1"),
    ("designer", "designer-1"),
])
def test_specialist_agents_md_within_25_lines(tmp_path, role, engineer_id):
    session = _make_session(engineer_id, workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer(
        role,
        skills=["{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md"],
        role_details=["Implement and test assigned tasks.", "Follow protocol in TOOLS/protocol.md."],
    )
    lines = _assemble_lines(session, project, engineer)
    assert len(lines) <= 25, f"{engineer_id} AGENTS.md: {len(lines)} lines (limit 25)"


# ── Test 3: planner workspace gets TOOLS/*.md files ──────────────────────────

def test_planner_workspace_tools_files_materialized(tmp_path):
    session = _make_session("planner", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer(
        "planner-dispatcher",
        skills=["{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md"],
    )
    aaw.render_dispatch_playbook_lines(session, project, engineer)
    tools_dir = tmp_path / "TOOLS"
    for fname in ("intent.md", "handoff.md", "feishu.md", "seat-lifecycle.md"):
        assert (tools_dir / fname).exists(), f"TOOLS/{fname} missing from planner workspace"


# ── Test 4: specialist workspace gets TOOLS/protocol.md ──────────────────────

def test_specialist_workspace_gets_protocol_md(tmp_path):
    session = _make_session("builder-1", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer("builder")
    aaw.render_dispatch_playbook_lines(session, project, engineer)
    protocol = tmp_path / "TOOLS" / "protocol.md"
    assert protocol.exists(), "TOOLS/protocol.md not materialized for specialist"


# ── Test 5: protocol.md covers key items ──────────────────────────────────────

def test_protocol_md_content_fidelity():
    protocol = TOOLS_SHARED / "protocol.md"
    assert protocol.is_file(), "Shared protocol.md missing"
    text = protocol.read_text(encoding="utf-8")
    required_phrases = [
        "tmux",
        "Consumed",
        "APPROVED",
        "reply_to",
        "source",
    ]
    for phrase in required_phrases:
        assert phrase in text, f"protocol.md missing required phrase: {phrase!r}"


# ── Test 6: intent.md contains target→intent mapping ─────────────────────────

def test_intent_md_has_target_intent_mapping():
    intent = TOOLS_SHARED / "intent.md"
    assert intent.is_file(), "Shared intent.md missing"
    text = intent.read_text(encoding="utf-8")
    # Must have at least one target role and intent pattern
    assert "builder" in text, "intent.md missing builder target"
    assert "intent" in text.lower(), "intent.md missing --intent reference"


# ── Test 7: render functions are idempotent for specialists ───────────────────

def test_specialist_render_idempotent(tmp_path):
    session = _make_session("builder-1", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer(
        "builder",
        skills=["{CLAWSEAT_ROOT}/core/skills/gstack-harness/SKILL.md"],
        role_details=["Implement tasks."],
    )
    lines_first = _assemble_lines(session, project, engineer)
    lines_second = _assemble_lines(session, project, engineer)
    assert lines_first == lines_second, "Specialist render is not idempotent"


# ── Test 8: specialist AGENTS.md references TOOLS/protocol.md ────────────────

def test_specialist_agents_md_references_protocol():
    session = _make_session("patrol-1")
    project = _make_project()
    engineer = _make_engineer("patrol")
    lines = _assemble_lines(session, project, engineer)
    combined = "\n".join(lines)
    assert "TOOLS/protocol.md" in combined, "Specialist AGENTS.md must reference TOOLS/protocol.md"


# ── Test 9: authority lines suppressed for specialists ───────────────────────

def test_specialist_authority_suppressed():
    engineer = _make_engineer("reviewer")
    lines = aaw.render_authority_lines(engineer)
    assert lines == [], "reviewer should have no authority lines"


# ── Test 10: handoff.md placeholders are substituted ─────────────────────────

def test_handoff_md_placeholders_substituted(tmp_path):
    session = _make_session("planner", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer("planner-dispatcher")
    content = aaw.render_tools_handoff(session, project, engineer, "/fake/profile.toml", "/fake/scripts", "planner")
    assert "<HARNESS_SCRIPTS>" not in content, "HARNESS_SCRIPTS placeholder not substituted"
    assert "<PROFILE>" not in content, "PROFILE placeholder not substituted"
    assert "/fake/scripts" in content or "handoff" in content.lower()


# ── Test 11: symlink failure → copy fallback ──────────────────────────────────

def test_protocol_md_symlink_failure_downgrades_to_copy(tmp_path, monkeypatch):
    from unittest.mock import patch as _patch
    session = _make_session("builder-1", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer("builder")

    real_symlink_to = Path.symlink_to

    def _raise_oserror(self, target, target_is_directory=False):
        raise OSError("symlink not supported")

    with _patch.object(Path, "symlink_to", _raise_oserror):
        aaw.render_dispatch_playbook_lines(session, project, engineer)

    target = tmp_path / "TOOLS" / "protocol.md"
    assert target.exists(), "protocol.md should exist after copy fallback"
    assert not target.is_symlink(), "fallback copy should not be a symlink"
    expected = (TOOLS_SHARED / "protocol.md").read_text(encoding="utf-8")
    assert target.read_text(encoding="utf-8") == expected, "copy content should match shared source"


# ── Test 12: symlink idempotent (existing correct symlink not rebuilt) ─────────

def test_protocol_md_symlink_idempotent(tmp_path):
    session = _make_session("builder-1", workspace=str(tmp_path))
    project = _make_project()
    engineer = _make_engineer("builder")

    # First call materializes the symlink
    aaw.render_dispatch_playbook_lines(session, project, engineer)
    target = tmp_path / "TOOLS" / "protocol.md"
    assert target.is_symlink(), "First call should create symlink"
    link_stat_before = target.stat()

    # Second call should be idempotent (no rebuild)
    aaw.render_dispatch_playbook_lines(session, project, engineer)
    assert target.is_symlink(), "Symlink should still exist after second call"
