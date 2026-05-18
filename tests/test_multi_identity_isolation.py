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
        if name in {
            "agent_admin_crud",
            "agent_admin_session",
            "project_binding",
            "project_tool_root",
            "real_home",
        }:
            sys.modules.pop(name, None)
    yield tmp_path


def _load_pb():
    import project_binding

    importlib.reload(project_binding)
    return project_binding


def _load_tool_root():
    import project_tool_root

    importlib.reload(project_tool_root)
    return project_tool_root


def _load_session():
    import agent_admin_session

    importlib.reload(agent_admin_session)
    return agent_admin_session


def _make_handlers(project_name: str, engineers: list[str]):
    import agent_admin_crud

    importlib.reload(agent_admin_crud)

    hooks = MagicMock()
    hooks.error_cls = RuntimeError
    hooks.load_project_or_current.return_value = SimpleNamespace(name=project_name, engineers=engineers)
    hooks.resolve_engineer_session.side_effect = [
        SimpleNamespace(
            engineer_id=engineer_id,
            project=project_name,
            session=f"{project_name}-{engineer_id}-claude",
        )
        for engineer_id in engineers
    ]
    hooks.session_service.reseed_sandbox_user_tool_dirs.return_value = [".lark-cli"]
    handlers = agent_admin_crud.CrudHandlers(hooks)
    return handlers, hooks


def _seed_lark(root: Path, text: str) -> None:
    (root / ".lark-cli").mkdir(parents=True, exist_ok=True)
    (root / ".lark-cli" / "config.json").write_text(text, encoding="utf-8")


def test_two_projects_per_project_have_separate_tool_roots(tmp_path: Path) -> None:
    pb = _load_pb()
    tool_root = _load_tool_root()
    aas = _load_session()

    pb.bind_project(project="smoke01", feishu_group_id="", tools_isolation="per-project")
    pb.bind_project(project="smoke02", feishu_group_id="", tools_isolation="per-project")

    source_one = tool_root.project_tool_root("smoke01")
    source_two = tool_root.project_tool_root("smoke02")
    _seed_lark(source_one, "smoke01")
    _seed_lark(source_two, "smoke02")

    runtime_one = tmp_path / "runtime-one" / "home"
    runtime_two = tmp_path / "runtime-two" / "home"
    runtime_one.mkdir(parents=True, exist_ok=True)
    runtime_two.mkdir(parents=True, exist_ok=True)

    aas.seed_user_tool_dirs(runtime_one, project_name="smoke01")
    aas.seed_user_tool_dirs(runtime_two, project_name="smoke02")

    assert (runtime_one / ".lark-cli").readlink() == source_one / ".lark-cli"
    assert (runtime_two / ".lark-cli").readlink() == source_two / ".lark-cli"

    (runtime_one / ".lark-cli" / "roundtrip.txt").write_text("only-smoke01", encoding="utf-8")
    assert (source_one / ".lark-cli" / "roundtrip.txt").read_text(encoding="utf-8") == "only-smoke01"
    assert not (source_two / ".lark-cli" / "roundtrip.txt").exists()


def test_switch_identity_reseed_does_not_affect_other_project(tmp_path: Path) -> None:
    pb = _load_pb()
    pb.bind_project(project="smoke01", feishu_group_id="")
    pb.bind_project(project="smoke02", feishu_group_id="")
    handlers, hooks = _make_handlers("smoke01", ["planner-1"])

    rc = handlers.project_switch_identity(
        SimpleNamespace(
            project="smoke01",
            tool="feishu",
            identity="<FEISHU_APP_ID>",
            dry_run=False,
        )
    )

    smoke01 = pb.load_binding("smoke01")
    smoke02 = pb.load_binding("smoke02")
    assert rc == 0
    assert smoke01 is not None and smoke01.feishu_sender_app_id == "<FEISHU_APP_ID>"
    assert smoke02 is not None and smoke02.feishu_sender_app_id == ""
    hooks.resolve_engineer_session.assert_called_once_with("planner-1", project_name="smoke01")
    hooks.session_service.reseed_sandbox_user_tool_dirs.assert_called_once()


def test_init_tools_source_project_copies_not_moves(tmp_path: Path) -> None:
    pb = _load_pb()
    tool_root = _load_tool_root()
    pb.bind_project(project="smoke02", feishu_group_id="")
    source_root = tool_root.project_tool_root("smoke01")
    _seed_lark(source_root, "source-project")
    handlers, hooks = _make_handlers("smoke02", ["planner-1"])

    rc = handlers.project_init_tools(
        SimpleNamespace(
            project="smoke02",
            from_source="real-home",
            source_project="smoke01",
            tools="lark-cli",
            dry_run=False,
        )
    )

    target_root = tool_root.project_tool_root("smoke02")
    assert rc == 0
    assert (target_root / ".lark-cli" / "config.json").read_text(encoding="utf-8") == "source-project"
    assert (source_root / ".lark-cli" / "config.json").read_text(encoding="utf-8") == "source-project"
    (target_root / ".lark-cli" / "config.json").write_text("target-only", encoding="utf-8")
    assert (source_root / ".lark-cli" / "config.json").read_text(encoding="utf-8") == "source-project"
    hooks.session_service.reseed_sandbox_user_tool_dirs.assert_called_once()
