from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest.mock import MagicMock

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agent_admin_commands import CommandHandlers  # noqa: E402
from agent_admin_crud import CrudHandlers  # noqa: E402


def _clear_caller_context(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CLAWSEAT_ENGINEER_PROFILE", "CLAWSEAT_ENGINEER_ID", "CLAWSEAT_SEAT"):
        monkeypatch.delenv(key, raising=False)


def _set_caller_context(monkeypatch: pytest.MonkeyPatch, profile_path: Path, *, seat_id: str = "planner") -> None:
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(profile_path))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", seat_id)
    monkeypatch.setenv("CLAWSEAT_SEAT", seat_id)


def _write_caller_profile(
    tmp_path: Path,
    *,
    seat_id: str = "planner",
    dispatch: bool = False,
    escalation: bool = False,
) -> Path:
    profile = tmp_path / f"{seat_id}.toml"
    profile.write_text(
        "\n".join(
            [
                "version = 1",
                f'id = "{seat_id}"',
                f'display_name = "{seat_id}"',
                f'role = "{seat_id}"',
                f"dispatch_authority = {'true' if dispatch else 'false'}",
                f"escalation_authority = {'true' if escalation else 'false'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return profile


def _base_crud_hooks(tmp_path: Path) -> MagicMock:
    hooks = MagicMock()
    hooks.error_cls = RuntimeError
    hooks.project_cls = SimpleNamespace
    hooks.engineer_cls = SimpleNamespace
    hooks.session_record_cls = SimpleNamespace
    hooks.normalize_name.side_effect = lambda value: value
    hooks.ensure_dir.side_effect = lambda path: Path(path).mkdir(parents=True, exist_ok=True)
    hooks.write_text.side_effect = lambda *args, **kwargs: None
    hooks.write_env_file.side_effect = lambda *args, **kwargs: None
    hooks.parse_env_file.return_value = {}
    hooks.load_toml.return_value = {}
    hooks.load_template.return_value = {"engineers": []}
    hooks.archive_if_exists.side_effect = lambda path, category: None
    hooks.ensure_secret_permissions.side_effect = lambda path: None
    hooks.load_projects.return_value = {}
    hooks.load_sessions.return_value = {}
    hooks.load_project_or_current.return_value = SimpleNamespace(
        name="install",
        engineers=[],
        monitor_engineers=[],
        seat_overrides={},
    )
    hooks.load_project.return_value = SimpleNamespace(name="install", engineers=[], monitor_engineers=[])
    hooks.engineer_path.side_effect = lambda engineer_id: tmp_path / "engineers" / engineer_id / "engineer.toml"
    hooks.session_path.side_effect = lambda project, engineer_id: (
        tmp_path / "sessions" / project / engineer_id / "session.toml"
    )
    hooks.session_service = MagicMock()
    return hooks


def _base_command_hooks(tmp_path: Path) -> MagicMock:
    hooks = MagicMock()
    hooks.error_cls = RuntimeError
    hooks.load_projects.return_value = {}
    hooks.get_current_project_name.return_value = None
    hooks.load_engineers.return_value = {}
    hooks.load_project_sessions.return_value = {}
    hooks.tmux_has_session.return_value = False
    hooks.open_monitor_window.side_effect = lambda *args, **kwargs: None
    hooks.open_dashboard_window.side_effect = lambda *args, **kwargs: None
    hooks.open_project_tabs_window.side_effect = lambda *args, **kwargs: None
    hooks.open_engineer_window.side_effect = lambda *args, **kwargs: None
    hooks.provision_session_heartbeat.side_effect = AssertionError("unexpected heartbeat request")
    hooks.load_project_or_current.return_value = SimpleNamespace(
        name="install",
        engineers=[],
        monitor_engineers=[],
        seat_overrides={},
        window_mode="tabs-1up",
    )
    hooks.session_service = MagicMock()
    return hooks


@dataclass(frozen=True)
class GuardCase:
    name: str
    authority: str
    sentinel_attr: str
    build: Callable[[Path], tuple[MagicMock, Callable[[], int], Callable[[], None]]]


def _build_crud_engineer_create(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_crud_hooks(tmp_path)
    project = SimpleNamespace(
        name="install",
        template_name="gstack-harness",
        engineers=["builder"],
        monitor_engineers=["builder"],
        seat_overrides={},
    )
    hooks.load_projects.return_value = {"install": project}
    hooks.create_engineer_profile.return_value = SimpleNamespace(engineer_id="builder")
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        tool="claude",
        auth_mode="oauth",
        provider="anthropic",
        identity="claude.oauth.anthropic.install.builder",
        workspace=str(tmp_path / "workspaces" / "install" / "builder"),
        runtime_dir=str(tmp_path / "runtime" / "builder"),
        session="install-builder-claude",
        bin_path="claude",
        monitor=True,
        legacy_sessions=[],
        launch_args=[],
        secret_file="",
        wrapper="",
    )
    hooks.create_session_record.return_value = session
    hooks.write_engineer.side_effect = lambda profile: None
    hooks.write_session.side_effect = lambda record: None
    hooks.apply_template.side_effect = lambda record, project_obj: None
    args = SimpleNamespace(
        project="install",
        engineer="builder",
        tool="claude",
        mode="oauth",
        provider="anthropic",
        no_monitor=False,
        profile=None,
        role=None,
    )

    def invoke() -> int:
        return CrudHandlers(hooks).engineer_create(args)

    def verify() -> None:
        assert hooks.create_engineer_profile.called
        assert hooks.write_session.called
        assert hooks.apply_template.called

    return hooks, invoke, verify


def _build_crud_engineer_delete(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_crud_hooks(tmp_path)
    project = SimpleNamespace(name="install", engineers=["builder"], monitor_engineers=["builder"])
    hooks.load_project.return_value = project
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        workspace=str(tmp_path / "workspaces" / "install" / "builder"),
        runtime_dir=str(tmp_path / "runtime" / "builder"),
        secret_file="",
        session="install-builder-claude",
    )
    hooks.resolve_engineer_session.return_value = session
    hooks.session_service.stop_engineer.side_effect = lambda session_obj, close_iterm_pane=True: None
    args = SimpleNamespace(engineer="builder", project="install")

    def invoke() -> int:
        return CrudHandlers(hooks).engineer_delete(args)

    def verify() -> None:
        assert hooks.session_service.stop_engineer.called
        assert project.engineers == []
        assert project.monitor_engineers == []

    return hooks, invoke, verify


def _build_crud_engineer_rename(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_crud_hooks(tmp_path)
    hooks.engineer_cls = SimpleNamespace
    hooks.session_record_cls = SimpleNamespace
    old = SimpleNamespace(
        engineer_id="builder",
        display_name="builder",
        aliases=["builder"],
        role="builder",
        role_details=["core"],
        skills=["shell"],
        human_facing=False,
        active_loop_owner=False,
        dispatch_authority=False,
        patrol_authority=False,
        unblock_authority=False,
        escalation_authority=False,
        remind_active_loop_owner=False,
        review_authority=False,
        design_authority=False,
        default_tool="claude",
        default_auth_mode="oauth",
        default_provider="anthropic",
    )
    hooks.resolve_engineer.return_value = old
    hooks.write_engineer.side_effect = lambda engineer: None
    hooks.write_session.side_effect = lambda session: None
    hooks.write_project.side_effect = lambda project: None
    hooks.load_sessions.return_value = {}
    hooks.archive_if_exists.side_effect = lambda path, category: None
    hooks.tmux_has_session.return_value = False
    hooks.load_project.return_value = SimpleNamespace(name="install", engineers=["builder"], monitor_engineers=["builder"])
    hooks.engineer_path.side_effect = lambda engineer_id: tmp_path / "engineers" / engineer_id / "engineer.toml"
    old_dir = hooks.engineer_path("builder").parent
    old_dir.mkdir(parents=True, exist_ok=True)
    args = SimpleNamespace(old="builder", new="builder-2")

    def invoke() -> int:
        return CrudHandlers(hooks).engineer_rename(args)

    def verify() -> None:
        assert hooks.write_engineer.called
        assert not old_dir.exists()

    return hooks, invoke, verify


def _build_crud_engineer_rebind(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_crud_hooks(tmp_path)
    hooks.load_project.return_value = SimpleNamespace(name="install")
    hooks.identity_name.side_effect = (
        lambda tool, mode, provider, engineer_id, project: f"{tool}.{mode}.{provider}.{project}.{engineer_id}"
    )
    hooks.runtime_dir_for_identity.side_effect = lambda tool, mode, identity: tmp_path / "runtime" / identity
    hooks.secret_file_for.side_effect = (
        lambda tool, provider, engineer_id: tmp_path / "secrets" / tool / provider / f"{engineer_id}.env"
    )
    hooks.write_env_file.side_effect = lambda path, values, ensure_dir, write_text: None
    hooks.write_session.side_effect = lambda session: None
    hooks.apply_template.side_effect = lambda session, project: None
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        tool="claude",
        auth_mode="oauth",
        provider="anthropic",
        identity="claude.oauth.anthropic.install.builder",
        workspace=str(tmp_path / "workspaces" / "install" / "builder"),
        runtime_dir=str(tmp_path / "runtime" / "old"),
        session="install-builder-claude",
        bin_path="claude",
        monitor=True,
        legacy_sessions=[],
        launch_args=[],
        secret_file="",
        wrapper="",
    )
    hooks.resolve_engineer_session.return_value = session
    args = SimpleNamespace(engineer="builder", project="install", tool="claude", mode="api", provider="minimax")

    def invoke() -> int:
        return CrudHandlers(hooks).engineer_rebind(args)

    def verify() -> None:
        assert session.auth_mode == "api"
        assert session.provider == "minimax"
        assert session.secret_file.endswith("builder.env")
        assert hooks.write_session.called

    return hooks, invoke, verify


def _build_crud_engineer_regenerate_workspace(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_crud_hooks(tmp_path)
    workspace = tmp_path / "workspaces" / "install" / "builder"
    workspace.mkdir(parents=True, exist_ok=True)
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        session="install-builder-codex",
        tool="codex",
        workspace=str(workspace),
    )
    hooks.resolve_engineer_session.return_value = session
    hooks.load_project.return_value = SimpleNamespace(name="install", engineers=["builder"], monitor_engineers=["builder"])
    hooks.render_template_text.return_value = {"AGENTS.md": "# builder\nupdated\n"}
    def apply_template(session_obj, project_obj) -> None:  # noqa: ARG001
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "AGENTS.md").write_text(
            hooks.render_template_text.return_value["AGENTS.md"],
            encoding="utf-8",
        )

    hooks.apply_template.side_effect = apply_template
    args = SimpleNamespace(project="install", engineer="builder", all_seats=False, yes=True)

    def invoke() -> int:
        return CrudHandlers(hooks).engineer_regenerate_workspace(args)

    def verify() -> None:
        assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "# builder\nupdated\n"
        assert hooks.apply_template.called

    return hooks, invoke, verify


def _build_crud_engineer_secret_set(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_crud_hooks(tmp_path)
    secret_file = tmp_path / "secrets" / "builder.env"
    secret_file.parent.mkdir(parents=True, exist_ok=True)
    secret_file.write_text("FOO=bar\n", encoding="utf-8")
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        auth_mode="api",
        secret_file=str(secret_file),
    )
    hooks.resolve_engineer_session.return_value = session
    hooks.parse_env_file.return_value = {"FOO": "bar"}
    captured: dict[str, object] = {}

    def write_env_file(path: Path, values: dict[str, str], ensure_dir, write_text) -> None:
        captured["path"] = Path(path)
        captured["values"] = dict(values)

    hooks.write_env_file.side_effect = write_env_file
    args = SimpleNamespace(engineer="builder", project="install", key="NEW_TOKEN", value="secret")

    def invoke() -> int:
        return CrudHandlers(hooks).engineer_secret_set(args)

    def verify() -> None:
        assert captured["path"] == secret_file
        values = captured["values"]
        assert values["FOO"] == "bar"
        assert values["NEW_TOKEN"] == "secret"

    return hooks, invoke, verify


def _build_command_session_start_engineer(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_command_hooks(tmp_path)
    project = SimpleNamespace(
        name="install",
        engineers=["builder"],
        monitor_engineers=["builder"],
        window_mode="tabs-1up",
        seat_overrides={},
    )
    hooks.load_project_or_current.return_value = project
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        session="install-builder-codex",
        tool="codex",
        auth_mode="oauth",
        provider="anthropic",
    )
    hooks.resolve_engineer_session.return_value = session
    started: list[tuple[str, bool]] = []
    hooks.session_service.start_engineer.side_effect = lambda session_obj, reset=False: started.append(
        (session_obj.engineer_id, reset)
    )
    args = SimpleNamespace(engineer="builder", project="install", reset=False, accept_override=False)

    def invoke() -> int:
        return CommandHandlers(hooks).session_start_engineer(args)

    def verify() -> None:
        assert started == [("builder", False)]
        hooks.provision_session_heartbeat.assert_not_called()

    return hooks, invoke, verify


def _build_command_session_batch_start_engineer(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_command_hooks(tmp_path)
    engineer_ids = ["builder", "designer"]
    project = SimpleNamespace(
        name="install",
        engineers=engineer_ids,
        monitor_engineers=engineer_ids,
        window_mode="tabs-1up",
        seat_overrides={},
    )
    hooks.load_project_or_current.return_value = project
    sessions = {
        engineer_id: SimpleNamespace(
            engineer_id=engineer_id,
            project="install",
            session=f"install-{engineer_id}-codex",
            tool="codex",
            auth_mode="oauth",
            provider="anthropic",
        )
        for engineer_id in engineer_ids
    }
    hooks.resolve_engineer_session.side_effect = lambda engineer_id, project_name=None: sessions[engineer_id]
    hooks.load_project_sessions.return_value = sessions
    hooks.load_engineers.return_value = {}
    started: list[tuple[str, bool]] = []
    hooks.session_service.start_engineer.side_effect = lambda session_obj, reset=False: started.append(
        (session_obj.engineer_id, reset)
    )
    args = SimpleNamespace(engineers=engineer_ids, project="install", reset=False, no_iterm=False, accept_override=False)

    def invoke() -> int:
        return CommandHandlers(hooks).session_batch_start_engineer(args)

    def verify() -> None:
        assert sorted(engineer_id for engineer_id, _ in started) == engineer_ids
        assert hooks.open_monitor_window.called
        hooks.provision_session_heartbeat.assert_not_called()

    return hooks, invoke, verify


def _build_command_session_stop_engineer(tmp_path: Path) -> tuple[MagicMock, Callable[[], int], Callable[[], None]]:
    hooks = _base_command_hooks(tmp_path)
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        session="install-builder-codex",
        tool="codex",
        auth_mode="oauth",
        provider="anthropic",
    )
    hooks.resolve_engineer_session.return_value = session
    stopped: list[tuple[str, bool]] = []
    hooks.session_service.stop_engineer.side_effect = lambda session_obj, close_iterm_pane=True: stopped.append(
        (session_obj.engineer_id, close_iterm_pane)
    )
    args = SimpleNamespace(engineer="builder", project="install", keep_iterm_tab=False)

    def invoke() -> int:
        return CommandHandlers(hooks).session_stop_engineer(args)

    def verify() -> None:
        assert stopped == [("builder", True)]

    return hooks, invoke, verify


AUTH_GUARD_CASES = [
    GuardCase("crud-engineer-create", "escalation", "load_projects", _build_crud_engineer_create),
    GuardCase("crud-engineer-delete", "escalation", "resolve_engineer_session", _build_crud_engineer_delete),
    GuardCase("crud-engineer-rename", "escalation", "resolve_engineer", _build_crud_engineer_rename),
    GuardCase("crud-engineer-rebind", "escalation", "resolve_engineer_session", _build_crud_engineer_rebind),
    GuardCase(
        "crud-engineer-regenerate-workspace",
        "escalation",
        "load_project",
        _build_crud_engineer_regenerate_workspace,
    ),
    GuardCase(
        "crud-engineer-secret-set",
        "escalation",
        "resolve_engineer_session",
        _build_crud_engineer_secret_set,
    ),
    GuardCase(
        "command-session-start-engineer",
        "dispatch",
        "resolve_engineer_session",
        _build_command_session_start_engineer,
    ),
    GuardCase(
        "command-session-batch-start-engineer",
        "dispatch",
        "resolve_engineer_session",
        _build_command_session_batch_start_engineer,
    ),
    GuardCase(
        "command-session-stop-engineer",
        "dispatch",
        "resolve_engineer_session",
        _build_command_session_stop_engineer,
    ),
]


@pytest.mark.parametrize("case", AUTH_GUARD_CASES, ids=lambda case: case.name)
def test_auth_guard_rejects_without_authority(case: GuardCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_caller_context(monkeypatch)
    hooks, invoke, _verify = case.build(tmp_path)
    sentinel = getattr(hooks, case.sentinel_attr)
    sentinel.side_effect = AssertionError(f"{case.name} should fail before touching {case.sentinel_attr}")

    with pytest.raises(RuntimeError, match=rf"requires .*{case.authority}_authority"):
        invoke()

    assert not sentinel.called


@pytest.mark.parametrize("case", AUTH_GUARD_CASES, ids=lambda case: case.name)
def test_auth_guard_allows_authorized_caller(case: GuardCase, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile_path = _write_caller_profile(
        tmp_path,
        seat_id="planner",
        dispatch=case.authority == "dispatch",
        escalation=case.authority == "escalation",
    )
    _set_caller_context(monkeypatch, profile_path)
    hooks, invoke, verify = case.build(tmp_path)

    assert invoke() == 0
    verify()


def _crud_cli_env(caller_profile: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("CLAWSEAT_ENGINEER_PROFILE", "CLAWSEAT_ENGINEER_ID", "CLAWSEAT_SEAT"):
        env.pop(key, None)
    if caller_profile is not None:
        env["CLAWSEAT_ENGINEER_PROFILE"] = str(caller_profile)
        env["CLAWSEAT_ENGINEER_ID"] = "planner"
        env["CLAWSEAT_SEAT"] = "planner"
    return env


def _run_crud_cli(
    command: str,
    target_profile: Path,
    caller_profile: Path | None,
    *extra_args: str,
    seat_id: str = "builder",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "agent_admin_crud.py"),
            command,
            seat_id,
            "--profile",
            str(target_profile),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO),
        env=_crud_cli_env(caller_profile),
        check=False,
    )


def _create_profile_text() -> str:
    return "\n".join(
        [
            "version = 1",
            'seats = ["planner"]',
            "",
            "[seat_roles]",
            'planner = "planner-dispatcher"',
            "",
            "[dynamic_roster]",
            'materialized_seats = ["planner"]',
            'runtime_seats = ["planner"]',
            "",
        ]
    )


def _rebind_profile_text() -> str:
    return "\n".join(
        [
            "version = 1",
            "",
            "[seat_overrides.builder]",
            'tool = "claude"',
            'auth_mode = "oauth"',
            'provider = "anthropic"',
            "",
        ]
    )


@pytest.mark.parametrize("command,target_text,extra_args,_expected_fragment", [
    (
        "engineer_create",
        _create_profile_text(),
        ["--role", "reviewer", "--tool", "claude", "--mode", "oauth", "--provider", "anthropic"],
        'reviewer-1 = "reviewer"',
    ),
    (
        "engineer_rebind",
        _rebind_profile_text(),
        ["--role", "builder", "--tool", "claude", "--mode", "api", "--provider", "minimax"],
        'provider = "minimax"',
    ),
], ids=["crud-create-cli", "crud-rebind-cli"])
def test_crud_cli_rejects_without_authority(
    command: str,
    target_text: str,
    extra_args: list[str],
    _expected_fragment: str,
    tmp_path: Path,
) -> None:
    target_profile = tmp_path / "target.toml"
    target_profile.write_text(target_text, encoding="utf-8")

    before = target_profile.read_text(encoding="utf-8")
    result = _run_crud_cli(command, target_profile, None, *extra_args)

    assert result.returncode != 0
    assert "CLAWSEAT_ENGINEER_PROFILE" in result.stderr
    assert "escalation_authority" in result.stderr
    assert target_profile.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("command,target_text,extra_args,expected_fragment", [
    (
        "engineer_create",
        _create_profile_text(),
        ["--role", "reviewer", "--tool", "claude", "--mode", "oauth", "--provider", "anthropic"],
        'reviewer-1 = "reviewer"',
    ),
    (
        "engineer_rebind",
        _rebind_profile_text(),
        ["--role", "builder", "--tool", "claude", "--mode", "api", "--provider", "minimax"],
        'provider = "minimax"',
    ),
], ids=["crud-create-cli-auth", "crud-rebind-cli-auth"])
def test_crud_cli_allows_authorized_caller(
    command: str,
    target_text: str,
    extra_args: list[str],
    expected_fragment: str,
    tmp_path: Path,
) -> None:
    caller_profile = _write_caller_profile(tmp_path, dispatch=False, escalation=True)
    target_profile = tmp_path / "target.toml"
    target_profile.write_text(target_text, encoding="utf-8")

    seat_id = "reviewer-1" if command == "engineer_create" else "builder"
    result = _run_crud_cli(command, target_profile, caller_profile, *extra_args, seat_id=seat_id)

    assert result.returncode == 0, result.stderr
    updated = target_profile.read_text(encoding="utf-8")
    assert expected_fragment in updated
    assert "error:" not in result.stderr
