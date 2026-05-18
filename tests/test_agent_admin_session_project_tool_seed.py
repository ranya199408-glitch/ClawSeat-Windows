from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "scripts"))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in list(sys.modules):
        if name in {"project_binding", "project_tool_root", "real_home", "agent_admin_session"}:
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


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_session = _HELPERS._make_session
_make_service = _HELPERS._make_service


def _seed_project_tools(root: Path) -> None:
    (root / ".lark-cli").mkdir(parents=True, exist_ok=True)
    (root / ".lark-cli" / "config.json").write_text("project-lark", encoding="utf-8")
    (root / ".config" / "gemini").mkdir(parents=True, exist_ok=True)
    (root / ".config" / "gemini" / "settings.json").write_text("gemini-settings", encoding="utf-8")
    (root / ".gemini").mkdir(parents=True, exist_ok=True)
    (root / ".gemini" / "auth.json").write_text("gemini-auth", encoding="utf-8")
    (root / ".config" / "codex").mkdir(parents=True, exist_ok=True)
    (root / ".config" / "codex" / "config.toml").write_text("model = 'gpt-5.4'", encoding="utf-8")
    (root / ".codex").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "auth.json").write_text("codex-auth", encoding="utf-8")
    (root / "Library" / "Application Support" / "iTerm2").mkdir(parents=True, exist_ok=True)
    (root / "Library" / "Application Support" / "iTerm2" / "state.txt").write_text("iterm", encoding="utf-8")
    (root / "Library" / "Preferences").mkdir(parents=True, exist_ok=True)
    (root / "Library" / "Preferences" / "com.googlecode.iterm2.plist").write_text("prefs", encoding="utf-8")


def test_seed_user_tool_dirs_prefers_project_tool_root_when_binding_says_per_project(tmp_path: Path):
    pb = _load_pb()
    tool_root = _load_tool_root()
    source_root = tool_root.project_tool_root("smoke01")
    source_root.mkdir(parents=True, exist_ok=True)
    _seed_project_tools(source_root)
    pb.bind_project(
        project="smoke01",
        feishu_group_id="",
        tools_isolation="per-project",
    )

    aas = _load_session()
    runtime_home = tmp_path / "runtime" / "home"
    runtime_home.mkdir(parents=True, exist_ok=True)

    changed = aas.seed_user_tool_dirs(runtime_home, project_name="smoke01")

    assert ".lark-cli" in changed
    assert ".config/gemini" in changed
    assert ".config/codex" in changed
    assert (runtime_home / ".lark-cli").is_symlink()
    assert (runtime_home / ".lark-cli").readlink() == source_root / ".lark-cli"
    assert (runtime_home / ".gemini").is_symlink()
    assert (runtime_home / ".gemini").readlink() == source_root / ".gemini"
    assert (runtime_home / ".codex").is_symlink()
    assert (runtime_home / ".codex").readlink() == source_root / ".codex"
    assert (runtime_home / "Library" / "Application Support" / "iTerm2").is_symlink()
    assert (
        runtime_home / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
    ).is_symlink()

    (runtime_home / ".lark-cli" / "roundtrip.txt").write_text("lark-write", encoding="utf-8")
    assert (source_root / ".lark-cli" / "roundtrip.txt").read_text(encoding="utf-8") == "lark-write"


def test_start_engineer_warns_when_project_tool_root_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pb = _load_pb()
    pb.bind_project(
        project="smoke01",
        feishu_group_id="",
        tools_isolation="per-project",
    )
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    session = _make_session(
        tmp_path,
        engineer_id="planner-1",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    session.project = "smoke01"
    svc, _hooks = _make_service(tmp_path, session)
    aas = _load_session()

    with (
        patch.object(aas.subprocess, "run", return_value=subprocess.CompletedProcess(["bash"], 0, "", "")),
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_run_tmux_with_retry"),
        patch.object(svc, "_configure_session_display"),
    ):
        svc.start_engineer(session)

    err = capsys.readouterr().err
    assert "project tool root missing for smoke01" in err
    assert "agent_admin project init-tools smoke01 --from real-home" in err
