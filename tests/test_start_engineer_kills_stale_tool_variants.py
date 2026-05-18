from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers_stale_tool", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_session = _HELPERS._make_session
_make_service = _HELPERS._make_service

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas  # noqa: E402


def test_start_engineer_kills_same_seat_stale_tool_variants_before_launcher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    session = _make_session(
        tmp_path,
        engineer_id="reviewer-1",
        tool="codex",
        auth_mode="api",
        provider="xcode-best",
        secret_content="OPENAI_API_KEY=<OPENAI_API_KEY>\n",
    )
    session.project = "smoke01"
    session.session = "smoke01-reviewer-1-codex"
    svc, _hooks = _make_service(tmp_path, session)

    events: list[str] = []

    def fake_launcher_run(cmd, **kwargs):
        events.append("launcher")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_tmux(args, **kwargs):
        command = " ".join(args)
        events.append(f"tmux:{command}")
        if args == ["list-sessions", "-F", "#{session_name}"]:
            stdout = "\n".join(
                [
                    session.session,
                    "smoke01-reviewer-1-claude",
                    "smoke01-reviewer-1-gemini",
                    "smoke01-builder-1-claude",
                    "install-reviewer-1-claude",
                ]
            )
            return subprocess.CompletedProcess(["tmux", *args], 0, stdout, "")
        if args[:2] == ["kill-session", "-t"]:
            return subprocess.CompletedProcess(["tmux", *args], 0, "", "")
        raise AssertionError(f"unexpected tmux args: {args}")

    monkeypatch.setattr(aas.subprocess, "run", fake_launcher_run)

    with (
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_configure_session_display"),
        patch.object(svc, "_run_tmux_with_retry", side_effect=fake_tmux),
    ):
        svc.start_engineer(session)

    assert events == [
        "tmux:list-sessions -F #{session_name}",
        "tmux:kill-session -t smoke01-reviewer-1-claude",
        "tmux:kill-session -t smoke01-reviewer-1-gemini",
        "launcher",
    ]
    err = capsys.readouterr().err
    assert "start-engineer: killed stale-tool session smoke01-reviewer-1-claude" in err
    assert "start-engineer: killed stale-tool session smoke01-reviewer-1-gemini" in err
    assert "smoke01-builder-1-claude" not in err
    assert "install-reviewer-1-claude" not in err


def test_start_engineer_ignores_no_such_session_race_for_stale_tool_variant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    session = _make_session(
        tmp_path,
        engineer_id="reviewer-1",
        tool="codex",
        auth_mode="api",
        provider="xcode-best",
        secret_content="OPENAI_API_KEY=<OPENAI_API_KEY>\n",
    )
    session.project = "smoke02"
    session.session = "smoke02-reviewer-1-codex"
    svc, _hooks = _make_service(tmp_path, session)

    events: list[str] = []

    def fake_launcher_run(cmd, **kwargs):
        events.append("launcher")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_tmux(args, **kwargs):
        command = " ".join(args)
        events.append(f"tmux:{command}")
        if args == ["list-sessions", "-F", "#{session_name}"]:
            return subprocess.CompletedProcess(
                ["tmux", *args],
                0,
                "smoke02-reviewer-1-claude\n",
                "",
            )
        if args == ["kill-session", "-t", "smoke02-reviewer-1-claude"]:
            return subprocess.CompletedProcess(
                ["tmux", *args],
                1,
                "",
                "can't find session: smoke02-reviewer-1-claude",
            )
        raise AssertionError(f"unexpected tmux args: {args}")

    monkeypatch.setattr(aas.subprocess, "run", fake_launcher_run)

    with (
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_configure_session_display"),
        patch.object(svc, "_run_tmux_with_retry", side_effect=fake_tmux),
    ):
        svc.start_engineer(session)

    assert events == [
        "tmux:list-sessions -F #{session_name}",
        "tmux:kill-session -t smoke02-reviewer-1-claude",
        "launcher",
    ]
    err = capsys.readouterr().err
    assert "killed stale-tool session" not in err


def test_start_engineer_kills_stale_tool_variants_for_install_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: fake_home))

    session = _make_session(
        tmp_path,
        engineer_id="reviewer-1",
        tool="codex",
        auth_mode="api",
        provider="xcode-best",
        secret_content="OPENAI_API_KEY=<OPENAI_API_KEY>\n",
    )
    svc, _hooks = _make_service(tmp_path, session)

    events: list[str] = []

    def fake_launcher_run(cmd, **kwargs):
        events.append("launcher")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_tmux(args, **kwargs):
        command = " ".join(args)
        events.append(f"tmux:{command}")
        if args == ["list-sessions", "-F", "#{session_name}"]:
            return subprocess.CompletedProcess(
                ["tmux", *args],
                0,
                "\n".join(
                    [
                        "install-reviewer-1-codex",
                        "install-reviewer-1-claude",
                        "install-builder-1-claude",
                    ]
                ),
                "",
            )
        if args == ["kill-session", "-t", "install-reviewer-1-claude"]:
            return subprocess.CompletedProcess(["tmux", *args], 0, "", "")
        raise AssertionError(f"unexpected tmux args: {args}")

    monkeypatch.setattr(aas.subprocess, "run", fake_launcher_run)

    with (
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_configure_session_display"),
        patch.object(svc, "_run_tmux_with_retry", side_effect=fake_tmux),
    ):
        svc.start_engineer(session)

    assert events == [
        "tmux:list-sessions -F #{session_name}",
        "tmux:kill-session -t install-reviewer-1-claude",
        "launcher",
    ]
    err = capsys.readouterr().err
    assert "start-engineer: killed stale-tool session install-reviewer-1-claude" in err
    assert "install-builder-1-claude" not in err
