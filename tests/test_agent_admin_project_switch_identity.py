from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "scripts"))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in list(sys.modules):
        if name in {"project_binding", "real_home", "agent_admin_crud"}:
            sys.modules.pop(name, None)
    yield tmp_path


def _load_pb():
    import project_binding

    importlib.reload(project_binding)
    return project_binding


def _make_handlers(project_name: str):
    import agent_admin_crud

    importlib.reload(agent_admin_crud)

    hooks = MagicMock()
    hooks.error_cls = RuntimeError
    hooks.load_project_or_current.return_value = SimpleNamespace(name=project_name, engineers=["planner-1"])
    hooks.resolve_engineer_session.return_value = SimpleNamespace(
        engineer_id="planner-1",
        project=project_name,
        session=f"{project_name}-planner-1-claude",
    )
    hooks.session_service.reseed_sandbox_user_tool_dirs.return_value = [".lark-cli"]
    handlers = agent_admin_crud.CrudHandlers(hooks)
    return handlers, hooks


@pytest.mark.parametrize(
    "tool, identity, expected_field",
    [
        ("feishu", "<FEISHU_APP_ID>", "feishu_sender_app_id"),
        ("gemini", "gemini@example.com", "gemini_account_email"),
        ("codex", "codex@example.com", "codex_account_email"),
    ],
)
def test_project_switch_identity_updates_binding_and_reseeds(tmp_path: Path, tool: str, identity: str, expected_field: str):
    pb = _load_pb()
    pb.bind_project(project="install", feishu_group_id="")
    handlers, hooks = _make_handlers("install")

    rc = handlers.project_switch_identity(
        SimpleNamespace(
            project="install",
            tool=tool,
            identity=identity,
            dry_run=False,
        )
    )

    assert rc == 0
    binding = pb.load_binding("install")
    assert binding is not None
    assert getattr(binding, expected_field) == identity
    assert binding.tools_isolation == "per-project"
    if tool == "feishu":
        assert binding.feishu_bot_account == identity
    hooks.session_service.reseed_sandbox_user_tool_dirs.assert_called_once()


def test_project_switch_identity_dry_run_reports_plan_without_writing(tmp_path: Path):
    pb = _load_pb()
    pb.bind_project(project="install", feishu_group_id="")
    handlers, hooks = _make_handlers("install")

    rc = handlers.project_switch_identity(
        SimpleNamespace(
            project="install",
            tool="feishu",
            identity="<FEISHU_APP_ID>",
            dry_run=True,
        )
    )

    assert rc == 0
    binding = pb.load_binding("install")
    assert binding is not None
    assert binding.feishu_sender_app_id == ""
    hooks.session_service.reseed_sandbox_user_tool_dirs.assert_not_called()

