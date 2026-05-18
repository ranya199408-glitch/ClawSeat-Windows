from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _render(tool: str) -> dict[str, str]:
    from agent_admin_template import TemplateHandlers, TemplateHooks

    engineer = SimpleNamespace(
        role="",
        role_details=[],
        aliases=[],
        skills=[],
    )
    hooks = TemplateHooks(
        ensure_dir=lambda path: None,
        write_text=lambda path, text: None,
        load_engineer=lambda seat: engineer,
        project_template_context=lambda project: None,
        q=lambda value: value,
        render_authority_lines=lambda engineer: [],
        render_protocol_reminder_lines=lambda engineer, role, **_: [],
        render_read_first_lines=lambda session, project, engineer: ["## Read First", "", "1. TODO.md"],
        render_harness_runtime_lines=lambda engineer: [],
        render_project_seat_map_lines=lambda *args, **kwargs: [],
        render_seat_boundary_lines=lambda session, engineer: ["## Boundary"],
        render_communication_protocol_lines=lambda engineer, project, **_: ["## Communication"],
        render_dispatch_playbook_lines=lambda session, project, engineer: [],
        render_loaded_skills_lines=lambda engineer, seat: [],
        render_optional_skills_catalog=lambda skills: "",
        workspace_contract_payload=lambda *args, **kwargs: {"ok": True},
        workspace_contract_fingerprint=lambda payload: "abc123",
        render_workspace_contract_text=lambda *args, **kwargs: "fingerprint = 'abc123'\n",
        render_role_line=lambda engineer, codex: "",
        render_role_details_lines=lambda engineer: [],
        render_aliases_lines=lambda engineer: [],
        render_heartbeat_text=lambda session, project, engineer: None,
        render_heartbeat_manifest_text=lambda *args, **kwargs: None,
    )
    session = SimpleNamespace(
        engineer_id="builder",
        tool=tool,
        workspace=str(_REPO / ".tmp-workspace"),
        auth_mode="oauth",
        provider="anthropic",
    )
    project = SimpleNamespace(
        name="install",
        repo_root=str(_REPO),
        tasks_root=str(_REPO / ".tasks"),
        profile_path="",
        template_name="clawseat-engineering",
    )
    return TemplateHandlers(hooks).render_template_text(tool, session, project)


def _assert_metadata_first_line(text: str) -> None:
    first = text.splitlines()[0]
    assert first.startswith("<!-- rendered_from_clawseat_sha=")
    assert "rendered_at=" in first
    assert "renderer_version=v1" in first
    assert "template_name=clawseat-engineering" in first


def test_rendered_claude_md_contains_sha_comment() -> None:
    rendered = _render("claude")

    _assert_metadata_first_line(rendered["CLAUDE.md"])


def test_rendered_agents_md_contains_sha_comment() -> None:
    rendered = _render("codex")

    _assert_metadata_first_line(rendered["AGENTS.md"])
