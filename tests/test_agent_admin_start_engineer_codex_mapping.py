from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas


def _make_launcher_path(tmp_path: Path) -> Path:
    launcher = tmp_path / "repo" / "core" / "launchers" / "agent-launcher.sh"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def _make_session(tmp_path: Path) -> SimpleNamespace:
    secret_file = tmp_path / "secret.env"
    secret_file.write_text("OPENAI_API_KEY=<OPENAI_API_KEY>\n", encoding="utf-8")
    return SimpleNamespace(
        engineer_id="reviewer-1",
        project="install",
        tool="codex",
        auth_mode="api",
        provider="xcode-best",
        identity="codex.api.xcode-best.install.reviewer-1",
        workspace=str(tmp_path / "workspace" / "reviewer-1"),
        runtime_dir="/tmp/legacy-runtime",
        session="install-reviewer-1-codex",
        secret_file=str(secret_file),
        wrapper="",
        _template_model="gpt-5.4",
    )


def _make_service(tmp_path: Path, session: SimpleNamespace) -> tuple[aas.SessionService, MagicMock]:
    hooks = MagicMock()
    hooks.agentctl_path = str(tmp_path / "repo" / "core" / "shell-scripts" / "agentctl.sh")
    hooks.launcher_path = str(_make_launcher_path(tmp_path))
    hooks.load_project.return_value = SimpleNamespace(name=session.project)
    hooks.reconcile_session_runtime.return_value = session
    hooks.tmux_has_session.return_value = False
    hooks.write_session = MagicMock()
    svc = aas.SessionService(hooks)
    return svc, hooks


def test_start_engineer_codex_xcode_best_maps_to_xcode_and_sets_seat_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    session = _make_session(tmp_path)
    svc, hooks = _make_service(tmp_path, session)
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs.get("env", {}))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    with (
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.start_engineer(session)

    stderr = capsys.readouterr().err
    cmd = captured["cmd"]
    env = captured["env"]
    assert cmd[5] == "--auth"
    assert cmd[6] == "xcode"
    assert "--custom-env-file" not in cmd
    assert env["CLAWSEAT_PROVIDER"] == "xcode-best"
    assert env["CLAWSEAT_SEAT"] == "reviewer-1"
    assert "start_engineer_launch:" in stderr
    assert "--auth xcode" in stderr
    assert "provider=xcode-best" in stderr
    hooks.write_session.assert_called_once()


def test_start_engineer_surfaces_launcher_nonzero_and_debug_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    session = _make_session(tmp_path)
    svc, _ = _make_service(tmp_path, session)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 23, "", "launcher exploded")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    with patch.object(svc, "_run_tmux_with_retry"):
        with pytest.raises(aas.SessionStartError, match="exit=23, detail=launcher exploded"):
            svc.start_engineer(session)

    stderr = capsys.readouterr().err
    assert "start_engineer_launch:" in stderr
    assert "--auth xcode" in stderr
