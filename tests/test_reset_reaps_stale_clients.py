from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_agent_admin_session_isolation_helpers_reset_clients",
    _HELPERS_PATH,
)
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


def test_clean_stale_attach_clients_skips_live_clients_and_new_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    svc, hooks = _make_service(tmp_path, session)
    hooks.tmux_has_session.return_value = True

    events: list[str] = []
    tmux_calls: list[str] = []

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["pgrep", "-f"]:
            events.append("pgrep")
            return subprocess.CompletedProcess(cmd, 0, "101\n202\n303\n404\n", "")
        if cmd[:1] == ["ps"]:
            pid = cmd[2]
            events.append(f"ps:{pid}")
            command_by_pid = {
                "101": "tmux attach -t =install-reviewer-1-codex",
                "202": "tmux attach -t =install-reviewer-1-codex",
                "303": "tmux new-session -d -s install-reviewer-1-codex",
                "404": "tmux attach -t =install-builder-1-claude",
            }
            return subprocess.CompletedProcess(cmd, 0, command_by_pid[pid], "")
        if cmd[:1] == ["kill"]:
            events.append(f"kill:{cmd[-1]}")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"unexpected subprocess command: {cmd}")

    def fake_tmux(args, **kwargs):
        tmux_calls.append("tmux:" + " ".join(args))
        return subprocess.CompletedProcess(["tmux", *args], 0, "101\n", "")

    monkeypatch.setattr(aas.subprocess, "run", fake_run)

    with patch.object(svc, "_run_tmux_with_retry", side_effect=fake_tmux):
        reaped = svc.clean_stale_attach_clients(session.session)

    assert reaped == [202]
    assert tmux_calls == [
        f"tmux:list-clients -t {session.session} -F #{{client_pid}}",
    ]
    assert events == [
        "pgrep",
        "ps:101",
        "ps:202",
        "ps:303",
        "ps:404",
        "kill:202",
    ]

