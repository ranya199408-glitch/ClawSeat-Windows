from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "scripts"
LIB = REPO / "core" / "lib"
for path in (SCRIPTS, LIB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_admin_commands import CommandHandlers, CommandHooks  # noqa: E402
from agent_admin_parser import ParserHooks, build_parser  # noqa: E402
from profile_validator import validate_profile_v2  # noqa: E402


@dataclass
class Session:
    engineer_id: str
    project: str
    tool: str
    auth_mode: str
    provider: str
    identity: str
    workspace: str
    runtime_dir: str
    session: str
    bin_path: str
    monitor: bool = True
    legacy_sessions: list[str] = field(default_factory=list)
    launch_args: list[str] = field(default_factory=list)
    secret_file: str = ""
    wrapper: str = ""


class _Service:
    def __init__(self) -> None:
        self.started: list[Session] = []
        self.stopped: list[Session] = []

    def start_engineer(self, session: Session, reset: bool = False) -> None:  # noqa: ARG002
        self.started.append(session)

    def stop_engineer(self, session: Session, close_iterm_pane: bool = True) -> None:  # noqa: ARG002
        self.stopped.append(session)


def _profile(path: Path, seats: list[str], extra: str = "") -> None:
    rendered = ", ".join(f'"{seat}"' for seat in seats)
    path.write_text(
        "version = 2\n"
        f"seats = [{rendered}]\n"
        'openclaw_frontstage_agent = "yu"\n'
        f"{extra}",
        encoding="utf-8",
    )


def test_profile_validator_rejects_qa_seat(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _profile(path, ["memory", "planner", "qa"])

    result = validate_profile_v2(path)

    assert not result.ok
    assert any("qa" in error for error in result.errors)


def test_profile_validator_rejects_numbered_qa_seat(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _profile(path, ["memory", "planner", "qa-1"])

    result = validate_profile_v2(path)

    assert not result.ok
    assert any("qa-1" in error for error in result.errors)


def test_profile_validator_rejects_qa_parallel_instances(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _profile(path, ["memory", "planner", "patrol"], '[parallel_instances]\nqa = 2\n')

    result = validate_profile_v2(path)

    assert not result.ok
    assert any("qa" in error for error in result.errors)


def test_parser_accepts_session_rename_command() -> None:
    def noop(_args):
        return 0

    hooks = ParserHooks(**{field: noop for field in ParserHooks.__dataclass_fields__})
    parser = build_parser(hooks)

    args = parser.parse_args(["session", "rename", "--project", "demo", "--from", "qa", "--to", "patrol"])

    assert args.project == "demo"
    assert args.from_seat == "qa"
    assert args.to_seat == "patrol"
    assert args.func is noop


def _rename_handlers(tmp_path: Path):
    project = SimpleNamespace(
        name="demo",
        engineers=["planner", "qa"],
        monitor_engineers=["qa"],
        seat_overrides={"qa": {"provider": "minimax"}},
    )
    old_workspace = tmp_path / "workspaces" / "demo" / "qa"
    old_runtime = tmp_path / "runtime" / "qa"
    old_secret = tmp_path / "secrets" / "qa.env"
    for path in (old_workspace, old_runtime):
        path.mkdir(parents=True)
        (path / "marker").write_text("x", encoding="utf-8")
    old_secret.parent.mkdir(parents=True)
    old_secret.write_text("ANTHROPIC_AUTH_TOKEN=sk-" + "B" * 24 + "\n", encoding="utf-8")
    old_session = Session(
        engineer_id="qa",
        project="demo",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        identity="old",
        workspace=str(old_workspace),
        runtime_dir=str(old_runtime),
        session="demo-qa-claude",
        bin_path="claude",
        secret_file=str(old_secret),
    )
    sessions = {"qa": old_session}
    written_sessions: list[Session] = []
    written_projects: list[SimpleNamespace] = []
    service = _Service()

    def session_path(project_name: str, seat: str) -> Path:
        return tmp_path / "sessions" / project_name / seat / "session.toml"

    session_path("demo", "qa").parent.mkdir(parents=True)
    session_path("demo", "qa").write_text("old", encoding="utf-8")

    hooks = CommandHooks(
        error_cls=RuntimeError,
        load_project_or_current=lambda _name: project,
        resolve_engineer_session=lambda *_args, **_kwargs: old_session,
        provision_session_heartbeat=lambda *_args, **_kwargs: (True, ""),
        load_project_sessions=lambda _project: sessions,
        tmux_has_session=lambda _name: False,
        load_projects=lambda: {"demo": project},
        get_current_project_name=lambda _projects: "demo",
        session_service=service,
        open_monitor_window=lambda *_args: None,
        open_dashboard_window=lambda *_args: None,
        open_project_tabs_window=lambda *_args: None,
        open_engineer_window=lambda *_args: None,
        load_engineers=lambda: {},
        write_project=written_projects.append,
        write_session=written_sessions.append,
        session_path=session_path,
        archive_if_exists=lambda path, _category: path.rename(path.with_name(path.name + ".archived")) if path.exists() else None,
        identity_name=lambda tool, auth, provider, seat, project_name: f"{tool}-{auth}-{provider}-{seat}-{project_name}",
        runtime_dir_for_identity=lambda *_args: tmp_path / "runtime" / "patrol",
        secret_file_for=lambda *_args: tmp_path / "secrets" / "patrol.env",
        session_name_for=lambda project_name, seat, tool: f"{project_name}-{seat}-{tool}",
        workspaces_root=tmp_path / "workspaces",
        ensure_dir=lambda path: path.mkdir(parents=True, exist_ok=True),
        ensure_secret_permissions=lambda path: path.chmod(0o600),
    )
    return CommandHandlers(hooks), project, service, written_sessions, written_projects, tmp_path


def test_session_rename_moves_runtime_files_and_starts_new_session(tmp_path: Path) -> None:
    handlers, _project, service, written_sessions, _written_projects, root = _rename_handlers(tmp_path)

    handlers.session_rename(SimpleNamespace(project="demo", from_seat="qa", to_seat="patrol"))

    assert written_sessions[0].engineer_id == "patrol"
    assert (root / "workspaces" / "demo" / "patrol" / "marker").is_file()
    assert (root / "runtime" / "patrol" / "marker").is_file()
    assert (root / "secrets" / "patrol.env").is_file()
    assert service.started[0].engineer_id == "patrol"


def test_session_rename_updates_project_roster_and_overrides(tmp_path: Path) -> None:
    handlers, project, _service, _written_sessions, written_projects, _root = _rename_handlers(tmp_path)

    handlers.session_rename(SimpleNamespace(project="demo", from_seat="qa", to_seat="patrol"))

    assert project.engineers == ["planner", "patrol"]
    assert project.monitor_engineers == ["patrol"]
    assert "qa" not in project.seat_overrides
    assert project.seat_overrides["patrol"] == {"provider": "minimax"}
    assert written_projects == [project]


def test_session_rename_kills_only_project_scoped_source_sessions(monkeypatch, tmp_path: Path) -> None:
    handlers, *_ = _rename_handlers(tmp_path)
    killed: list[str] = []

    def fake_run(cmd, **_kwargs):
        if cmd[:2] == ["tmux", "list-sessions"]:
            return subprocess.CompletedProcess(cmd, 0, "demo-qa-claude\ndemo2-qa-claude\ndemo-builder-claude\n", "")
        if cmd[:2] == ["tmux", "kill-session"]:
            killed.append(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr("agent_admin_commands.subprocess.run", fake_run)

    assert handlers._kill_project_scoped_sessions("demo", "qa") == ["demo-qa-claude"]
    assert killed == ["=demo-qa-claude"]


def test_removed_alias_module_is_absent() -> None:
    assert not (SCRIPTS / "patrol_alias.py").exists()


def test_patrol_launch_agent_template_uses_patrol_label() -> None:
    text = (REPO / "core" / "templates" / "patrol.plist.in").read_text(encoding="utf-8")

    assert "com.clawseat.{PROJECT}.patrol" in text
    assert "qa-patrol" not in text


def test_install_uses_patrol_launch_agent_template() -> None:
    text = (REPO / "scripts" / "install.sh").read_text(encoding="utf-8")

    assert "core/templates/patrol.plist.in" in text
    assert "com.clawseat.${PROJECT}.patrol" in text
