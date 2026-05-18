from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas  # noqa: E402
from agent_admin_commands import CommandHandlers  # noqa: E402


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_session = _HELPERS._make_session
_make_service = _HELPERS._make_service


def test_start_engineer_reseeds_existing_sandbox_home_before_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_home = tmp_path / "real_home"
    fake_home = tmp_path / "sandbox_home"
    real_home.mkdir(parents=True)
    fake_home.mkdir(parents=True)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    (real_home / ".lark-cli").mkdir(parents=True, exist_ok=True)
    (real_home / ".lark-cli" / "config.json").write_text("real", encoding="utf-8")

    session = _make_session(
        tmp_path,
        engineer_id="planner-1",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    svc, hooks = _make_service(tmp_path, session)

    runtime_home = (
        real_home
        / ".agent-runtime"
        / "identities"
        / "claude"
        / "api"
        / "minimax-install-planner-1-claude"
        / "home"
    )
    runtime_home.mkdir(parents=True, exist_ok=True)
    (runtime_home / ".lark-cli").mkdir(parents=True, exist_ok=True)
    (runtime_home / ".lark-cli" / "sentinel.txt").write_text("keep-me", encoding="utf-8")

    launcher_calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        launcher_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    with (
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.start_engineer(session)

    assert launcher_calls, "launcher was not invoked"
    assert (runtime_home / ".lark-cli").is_symlink()
    assert (runtime_home / ".lark-cli").readlink() == real_home / ".lark-cli"

    backups = list((runtime_home / ".sandbox-pre-seed-backup").rglob("sentinel.txt"))
    assert backups
    assert any(path.read_text(encoding="utf-8") == "keep-me" for path in backups)
    hooks.write_session.assert_called()


def test_session_reseed_sandbox_command_reseeds_all_project_seats(capsys: pytest.CaptureFixture[str]) -> None:
    def _reseed(session: SimpleNamespace) -> list[str]:
        return [".lark-cli", ".gemini"] if session.engineer_id == "planner-1" else []

    hooks = SimpleNamespace(
        error_cls=RuntimeError,
        load_project_or_current=lambda project: SimpleNamespace(
            name=project or "smoke01",
            engineers=["planner-1", "builder-1"],
        ),
        resolve_engineer_session=lambda engineer_id, project_name=None: SimpleNamespace(
            engineer_id=engineer_id,
            project=project_name or "smoke01",
            session=f"{project_name or 'smoke01'}-{engineer_id}-claude",
        ),
        session_service=SimpleNamespace(
            reseed_sandbox_user_tool_dirs=_reseed,
        ),
    )
    handlers = CommandHandlers(hooks)

    rc = handlers.session_reseed_sandbox(SimpleNamespace(project="smoke01", all=True, engineers=[]))
    out = capsys.readouterr().out

    assert rc == 0
    assert "planner-1: .lark-cli, .gemini" in out
    assert "builder-1:" not in out
