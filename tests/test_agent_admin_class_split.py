from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas  # noqa: E402
from agent_admin_crud import CrudHandlers  # noqa: E402
from agent_admin_crud_bootstrap import BootstrapCrud  # noqa: E402
from agent_admin_crud_engineer import EngineerCrud  # noqa: E402
from agent_admin_crud_project import ProjectCrud  # noqa: E402
from agent_admin_crud_validation import ValidationCrud  # noqa: E402
from agent_admin_session_launcher import SessionLaunchEnv  # noqa: E402
from agent_admin_session_lifecycle import SessionStartLifecycle  # noqa: E402
from agent_admin_session_recovery import SessionRecovery  # noqa: E402


@pytest.fixture(autouse=True)
def _caller_escalation_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "caller.toml"
    profile.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "planner"',
                'display_name = "planner"',
                'role = "planner"',
                "dispatch_authority = false",
                "escalation_authority = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")


def test_crud_handlers_api_unchanged():
    handlers = CrudHandlers(SimpleNamespace(error_cls=RuntimeError))

    assert isinstance(handlers.project, ProjectCrud)
    assert isinstance(handlers.engineer, EngineerCrud)
    assert isinstance(handlers.bootstrap, BootstrapCrud)
    assert isinstance(handlers.validation, ValidationCrud)

    routing = {
        "project_create": handlers.project,
        "project_show": handlers.project,
        "engineer_create": handlers.engineer,
        "engineer_regenerate_workspace": handlers.engineer,
        "project_bootstrap": handlers.bootstrap,
        "project_validate": handlers.validation,
        "project_koder_bind": handlers.validation,
        "project_binding_show": handlers.validation,
    }
    args = SimpleNamespace()

    for public_name, target in routing.items():
        if public_name == "project_show":
            public_name = "project_open"

        calls: list[object] = []

        def fake_method(received_args, *, _calls=calls, _name=public_name):
            _calls.append(received_args)
            return f"{_name}:ok"

        setattr(target, public_name, fake_method)

        assert getattr(handlers, public_name)(args) == f"{public_name}:ok"
        assert calls == [args]


def test_session_service_delegation_works():
    hooks = SimpleNamespace(tmux_has_session=lambda session_name: session_name == "demo-seat")
    service = aas.SessionService(hooks)

    assert isinstance(service, SessionRecovery)
    assert isinstance(service, SessionStartLifecycle)
    assert isinstance(service, SessionLaunchEnv)

    assert "start_engineer" not in aas.SessionService.__dict__
    assert aas.SessionService.start_engineer is SessionStartLifecycle.start_engineer
    assert aas.SessionService._custom_env_payload is SessionLaunchEnv._custom_env_payload
    assert aas.SessionService.start_project is SessionRecovery.start_project

    assert service.status(SimpleNamespace(session="demo-seat")) == "running"
    assert service.status(SimpleNamespace(session="missing-seat")) == "stopped"
    assert service._launcher_auth_for(
        SimpleNamespace(tool="codex", auth_mode="oauth", provider="openai")
    ) == "chatgpt"


def test_session_service_preserves_reload_patch_globals(tmp_path, monkeypatch):
    service = aas.SessionService(SimpleNamespace())
    monkeypatch.setitem(service._compat_module_globals, "real_user_home", lambda: tmp_path)

    session = SimpleNamespace(tool="claude", session="demo-planner-claude")

    assert service._launcher_runtime_dir(session, "oauth_token") == (
        tmp_path
        / ".agent-runtime"
        / "identities"
        / "claude"
        / "oauth_token"
        / "oauth_token-demo-planner-claude"
    )
