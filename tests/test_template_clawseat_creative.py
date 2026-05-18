from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin as aa  # noqa: E402
from agent_admin_commands import CommandHandlers  # noqa: E402


_TEMPLATE = _REPO / "templates" / "clawseat-creative.toml"
_INSTALL = _REPO / "scripts" / "install.sh"
_EXPECTED_SEATS = [
    "memory",
    "writer",
    "builder-image",
    "builder-av",
    "patrol",
]


@pytest.fixture(autouse=True)
def _caller_dispatch_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "caller.toml"
    profile.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "planner"',
                'display_name = "planner"',
                'role = "planner"',
                "dispatch_authority = true",
                "escalation_authority = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")


def _load_template() -> dict:
    with _TEMPLATE.open("rb") as handle:
        return tomllib.load(handle)


def _clawseat_creative_project(name: str = "team-demo") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        repo_root=str(_REPO),
        monitor_session=f"{name}-memory",
        engineers=list(_EXPECTED_SEATS),
        monitor_engineers=list(_EXPECTED_SEATS),
        template_name="clawseat-creative",
        declared_skills=["TOOLS/memory.md"],
        seat_overrides={},
        window_mode="split-2",
        monitor_max_panes=5,
        open_detail_windows=False,
        profile_path=str(_REPO / "profiles" / f"{name}.toml"),
    )


def _isolate_store_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aa.STORE_HANDLERS.hooks, "engineers_root", tmp_path / "engineers")
    monkeypatch.setattr(aa.STORE_HANDLERS.hooks, "sessions_root", tmp_path / "sessions")
    monkeypatch.setattr(aa.STORE_HANDLERS.hooks, "workspaces_root", tmp_path / "workspaces")
    monkeypatch.setattr(
        aa.STORE_HANDLERS.hooks,
        "runtime_dir_for_identity",
        lambda tool, auth_mode, identity: tmp_path / "runtime" / identity,
    )
    monkeypatch.setattr(
        aa.STORE_HANDLERS.hooks,
        "secret_file_for",
        lambda tool, provider, engineer_id: tmp_path / "secrets" / tool / provider / f"{engineer_id}.env",
    )
    monkeypatch.setattr(
        aa.STORE_HANDLERS.hooks,
        "identity_name",
        lambda tool, auth_mode, provider, engineer_id, project: f"{tool}.{auth_mode}.{provider}.{project}.{engineer_id}",
    )
    monkeypatch.setattr(
        aa.STORE_HANDLERS.hooks,
        "session_name_for",
        lambda project, engineer_id, tool: f"{project}-{engineer_id}-{tool}",
    )


def _clawseat_creative_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_name: str = "team-demo",
) -> tuple[SimpleNamespace, dict[str, aa.Engineer], list[str], list[dict[str, object]]]:
    _isolate_store_paths(tmp_path, monkeypatch)
    project = _clawseat_creative_project(project_name)
    context = aa.project_template_context(project)
    assert context is not None
    profiles, engineer_order, optional_skills = context
    return project, profiles, engineer_order, optional_skills


def _render_agents_md(
    seat_id: str,
    project: SimpleNamespace,
    profiles: dict[str, aa.Engineer],
    engineer_order: list[str],
) -> str:
    engineer = profiles[seat_id]
    session = aa.create_session_record(
        seat_id,
        project,
        engineer.default_tool,
        engineer.default_auth_mode,
        engineer.default_provider,
        monitor=True,
    )
    rendered = aa.render_template_text(
        session.tool,
        session,
        project,
        engineer_override=engineer,
        project_engineers=profiles,
        engineer_order=engineer_order,
    )
    return rendered["AGENTS.md"]


def test_clawseat_creative_template_schema_has_five_seats() -> None:
    data = _load_template()

    assert data["version"] == 1
    assert data["template_name"] == "clawseat-creative"
    assert data["defaults"]["window_mode"] == "split-2"
    assert data["defaults"]["monitor_max_panes"] == 5
    assert data["defaults"]["workspace_tools"] == ["TOOLS/memory.md"]
    assert data["window_layout"]["workers_grid"]["left_main_seat"] == "writer"
    assert data["window_layout"]["workers_grid"]["right_seats"] == ["builder-image", "builder-av", "patrol"]
    assert [engineer["id"] for engineer in data["engineers"]] == _EXPECTED_SEATS
    assert data["engineers"][0]["role"] == "project-memory"
    assert data["engineers"][1]["tool"] == "claude"      # writer
    assert data["engineers"][2]["tool"] == "codex"       # builder-image
    assert data["engineers"][3]["tool"] == "gemini"      # builder-av
    assert data["engineers"][3]["provider"] == "google"  # gemini oauth for YouTube reference learning
    assert data["engineers"][4]["patrol_authority"] is True


def test_clawseat_creative_template_declared_skills_include_cartooner_core() -> None:
    """clawseat-creative is cartooner-bound — declared_skills must include the core cartooner family."""
    data = _load_template()
    declared = data["defaults"]["declared_skills"]
    assert isinstance(declared, list)
    for required in (
        "cartooner",
        "cartooner-image",
        "cartooner-video",
        "cartooner-audio",
        "cartooner-storyboard",
        "cartooner-design",
        "cartooner-prompt",
    ):
        assert required in declared, f"missing required cartooner skill in declared_skills: {required}"


def test_clawseat_creative_seats_bind_cartooner_skills() -> None:
    """Each seat references only the cartooner-* skills relevant to its craft (no skill bloat)."""
    data = _load_template()
    seat_skills = {engineer["id"]: engineer.get("skills", []) for engineer in data["engineers"]}

    # builder-image: cartooner image family + nano-banana / gpt-image-2 fallback;
    # cartooner-prompt is NOT installed here (it's video-prompt focused)
    image_skills = seat_skills["builder-image"]
    assert any("cartooner-image" in s for s in image_skills)
    assert any("cartooner-storyboard" in s for s in image_skills)
    assert any("cartooner-design" in s for s in image_skills)
    assert any("nano-banana" in s for s in image_skills)
    assert any("gpt-image-2" in s for s in image_skills)
    assert not any("cartooner-prompt" in s for s in image_skills), \
        "cartooner-prompt is video-side; should not be installed on builder-image"

    # builder-av: video + audio + Seedance cookbook + cartooner-prompt
    av_skills = seat_skills["builder-av"]
    assert any("cartooner-video" in s for s in av_skills)
    assert any("cartooner-audio" in s for s in av_skills)
    assert any("cartooner-prompt" in s for s in av_skills)
    assert any("cartooner-seedance-cookbook" in s for s in av_skills)

    # patrol: minimal — only cartooner-harness + cartooner-resource-ops
    patrol_skills = seat_skills["patrol"]
    assert any("cartooner-resource-ops" in s for s in patrol_skills)
    assert len(patrol_skills) == 2, "patrol stays minimal — no gstack patrol/tmux-basics"

    # memory: router + resource-ops; does NOT install clawseat-memory or memory-oracle
    memory_skills = seat_skills["memory"]
    assert any("cartooner/SKILL.md" in s for s in memory_skills), "memory must load cartooner router"
    assert any("cartooner-resource-ops" in s for s in memory_skills)
    assert not any("clawseat-memory" in s for s in memory_skills), \
        "clawseat-memory is engineering-bound; cartooner-harness self-contains memory behaviors"
    assert not any("memory-oracle" in s for s in memory_skills), \
        "memory-oracle (cross-project) is not needed in cartooner v1"

    # writer: pure literary — cartooner-script-development + viral-copywriter
    writer_skills = seat_skills["writer"]
    assert any("cartooner-script-development" in s for s in writer_skills)
    assert any("viral-copywriter" in s for s in writer_skills)


def test_clawseat_creative_project_template_context_loads_five_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, profiles, engineer_order, optional_skills = _clawseat_creative_context(tmp_path, monkeypatch)

    assert list(profiles) == _EXPECTED_SEATS
    assert engineer_order == _EXPECTED_SEATS
    assert isinstance(optional_skills, list)
    assert profiles["memory"].role == "project-memory"
    assert profiles["memory"].default_tool == "claude"
    assert profiles["memory"].default_auth_mode == "api"
    assert profiles["memory"].default_provider == "minimax"
    assert profiles["writer"].default_tool == "claude"
    assert profiles["writer"].default_auth_mode == "oauth_token"
    assert profiles["builder-image"].default_tool == "codex"
    assert profiles["builder-image"].default_auth_mode == "oauth"
    assert profiles["builder-av"].default_tool == "gemini"
    assert profiles["builder-av"].default_auth_mode == "oauth"
    assert profiles["builder-av"].default_provider == "google"
    assert profiles["patrol"].patrol_authority is True
    assert project.template_name == "clawseat-creative"


@pytest.mark.parametrize(
    ("seat_id", "expected_role_fragment", "expected_skill_path", "expected_marker"),
    [
        # memory uses cartooner memory variant template (Vision Steward) and loads cartooner-harness SKILL via template-aware role_hint override
        pytest.param("memory", "Vision Steward", "core/skills/cartooner-harness/SKILL.md", "process-automation engine", id="memory"),
        # creative seats map to cartooner-harness/SKILL.md (cartooner-bound boundary)
        pytest.param("writer", "Role: `screenwriter`", "core/skills/cartooner-harness/SKILL.md", "Story Specialist", id="writer"),
        pytest.param("builder-image", "Role: `builder-image`", "core/skills/cartooner-harness/SKILL.md", "Image Specialist", id="builder-image"),
        pytest.param("builder-av", "Role: `builder-av`", "core/skills/cartooner-harness/SKILL.md", "AV Cinematographer", id="builder-av"),
        # patrol on creative loads cartooner-harness role contract (Asset Guardian) via the template-aware override
        pytest.param("patrol", "Role: `patrol`", "core/skills/cartooner-harness/SKILL.md", "Asset Guardian", id="patrol"),
    ],
)
def test_clawseat_creative_rendered_workspace_embeds_role_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seat_id: str,
    expected_role_fragment: str,
    expected_skill_path: str,
    expected_marker: str,
) -> None:
    project, profiles, engineer_order, _optional_skills = _clawseat_creative_context(tmp_path, monkeypatch)

    agents_md = _render_agents_md(seat_id, project, profiles, engineer_order)
    assert expected_role_fragment in agents_md
    # Memory uses the cartooner variant template (workspace-memory-cartooner.template.md)
    # which embeds the Vision Steward role contract inline instead of appending a
    # separate "## Role SKILL (canonical)" wrapper. Other seats keep the wrapper.
    if seat_id != "memory":
        assert "## Role SKILL (canonical)" in agents_md
    assert expected_skill_path in agents_md
    assert expected_marker in agents_md


def test_clawseat_creative_install_sh_dry_run_accepts_template(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = subprocess.run(
        [
            "bash",
            str(_INSTALL),
            "--project",
            "clawseat-creative-smoke",
            "--template",
            "clawseat-creative",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHON_BIN": sys.executable,
        },
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "CLAWSEAT_TEMPLATE_NAME=clawseat-creative" in combined
    assert "clawseat-creative" in combined
    assert "INVALID_TEMPLATE" not in combined


def test_clawseat_creative_batch_start_engineer_accepts_all_five_seats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project, profiles, _engineer_order, _optional_skills = _clawseat_creative_context(tmp_path, monkeypatch)
    monkeypatch.setattr(CommandHandlers, "_require_dispatch_authority", lambda self, action: None)

    started: list[tuple[str, bool]] = []
    lock = threading.Lock()

    class _FakeSessionService:
        def start_engineer(self, session, reset: bool = False) -> None:  # noqa: ARG002
            with lock:
                started.append((session.engineer_id, reset))

    hooks = MagicMock()
    hooks.error_cls = RuntimeError
    hooks.load_project_or_current.return_value = project
    hooks.resolve_engineer_session.side_effect = (
        lambda engineer_id, project_name=None: aa.create_session_record(
            engineer_id,
            project,
            profiles[engineer_id].default_tool,
            profiles[engineer_id].default_auth_mode,
            profiles[engineer_id].default_provider,
            monitor=True,
        )
    )
    hooks.provision_session_heartbeat.return_value = (True, "")
    hooks.session_service = _FakeSessionService()
    hooks.load_project_sessions.return_value = {}
    hooks.tmux_has_session.return_value = False
    hooks.load_projects.return_value = {}
    hooks.get_current_project_name.return_value = None
    hooks.load_engineers.return_value = profiles
    hooks.open_monitor_window.side_effect = AssertionError("unexpected monitor open")
    hooks.open_dashboard_window.side_effect = AssertionError("unexpected dashboard open")
    hooks.open_project_tabs_window.side_effect = AssertionError("unexpected project tabs open")
    hooks.open_engineer_window.side_effect = AssertionError("unexpected engineer window open")

    handlers = CommandHandlers(hooks)
    rc = handlers.session_batch_start_engineer(
        SimpleNamespace(
            project=project.name,
            engineers=list(_EXPECTED_SEATS),
            reset=False,
            no_iterm=True,
            accept_override=False,
        )
    )

    assert rc == 0
    assert sorted(engineer_id for engineer_id, _ in started) == sorted(_EXPECTED_SEATS)
    assert all(reset is False for _engineer_id, reset in started)
    assert len(started) == len(_EXPECTED_SEATS)


def test_patrol_skill_requires_memory_notifications_and_no_direct_builder_pokes() -> None:
    text = (_REPO / "core" / "skills" / "patrol" / "SKILL.md").read_text(encoding="utf-8")
    assert "review" in text.lower()
    assert "通知 memory" in text
    assert "禁直戳 builder" in text


