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
        if name in {"project_binding", "project_tool_root", "real_home", "agent_admin_crud"}:
            sys.modules.pop(name, None)
    yield tmp_path


def _load_pb():
    import project_binding

    importlib.reload(project_binding)
    return project_binding


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
    hooks.session_service.reseed_sandbox_user_tool_dirs.return_value = [".lark-cli", ".gemini"]
    handlers = agent_admin_crud.CrudHandlers(hooks)
    return handlers, hooks


def _seed_real_home(root: Path) -> None:
    (root / ".lark-cli").mkdir(parents=True, exist_ok=True)
    (root / ".lark-cli" / "config.json").write_text("real-lark", encoding="utf-8")
    (root / ".config" / "gemini").mkdir(parents=True, exist_ok=True)
    (root / ".config" / "gemini" / "settings.json").write_text("real-gemini", encoding="utf-8")
    (root / ".gemini").mkdir(parents=True, exist_ok=True)
    (root / ".gemini" / "auth.json").write_text("real-gemini-auth", encoding="utf-8")
    (root / ".config" / "codex").mkdir(parents=True, exist_ok=True)
    (root / ".config" / "codex" / "config.toml").write_text("model = 'gpt-5.4'", encoding="utf-8")
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "auth.json").write_text("real-codex-auth", encoding="utf-8")
    (root / "Library" / "Application Support" / "iTerm2").mkdir(parents=True, exist_ok=True)
    (root / "Library" / "Application Support" / "iTerm2" / "state.txt").write_text("iterm", encoding="utf-8")
    (root / "Library" / "Preferences").mkdir(parents=True, exist_ok=True)
    (root / "Library" / "Preferences" / "com.googlecode.iterm2.plist").write_text("prefs", encoding="utf-8")


def test_project_init_tools_copies_real_home_into_project_root_and_reseeds(tmp_path: Path, capsys):
    pb = _load_pb()
    real_home = tmp_path
    _seed_real_home(real_home)
    pb.bind_project(project="install", feishu_group_id="")
    handlers, hooks = _make_handlers("install", ["planner-1"])

    rc = handlers.project_init_tools(
        SimpleNamespace(
            project="install",
            from_source="real-home",
            source_project="",
            tools="lark-cli,gemini,codex,iterm2",
            dry_run=False,
        )
    )

    assert rc == 0
    target_root = real_home / ".agent-runtime" / "projects" / "install"
    assert (target_root / ".lark-cli" / "config.json").read_text(encoding="utf-8") == "real-lark"
    assert (target_root / ".gemini" / "auth.json").read_text(encoding="utf-8") == "real-gemini-auth"
    assert (target_root / ".codex" / "auth.json").read_text(encoding="utf-8") == "real-codex-auth"
    assert (
        target_root / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
    ).read_text(encoding="utf-8") == "prefs"

    binding = pb.load_binding("install")
    assert binding is not None
    assert binding.tools_isolation == "per-project"
    hooks.session_service.reseed_sandbox_user_tool_dirs.assert_called_once()
    assert "project init-tools updated" in capsys.readouterr().out


def test_project_init_tools_dry_run_reports_plan_without_writing(tmp_path: Path, capsys):
    pb = _load_pb()
    pb.bind_project(project="install", feishu_group_id="")
    handlers, hooks = _make_handlers("install", ["planner-1"])

    rc = handlers.project_init_tools(
        SimpleNamespace(
            project="install",
            from_source="empty",
            source_project="",
            tools="lark-cli",
            dry_run=True,
        )
    )

    assert rc == 0
    assert not (tmp_path / ".agent-runtime" / "projects" / "install").exists()
    hooks.session_service.reseed_sandbox_user_tool_dirs.assert_not_called()
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "lark-cli" in out

