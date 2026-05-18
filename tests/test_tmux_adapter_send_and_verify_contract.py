from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from core.harness_adapter import SessionHandle

_REPO = Path(__file__).resolve().parents[1]
_ADAPTER_PATH = _REPO / "adapters" / "harness" / "tmux-cli" / "adapter.py"

_spec = importlib.util.spec_from_file_location("tmux_cli_adapter", _ADAPTER_PATH)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
TmuxCliAdapter = _module.TmuxCliAdapter


def _handle() -> SessionHandle:
    return SessionHandle(
        seat_id="builder",
        project="demo",
        tool="claude",
        runtime_id="demo-builder-claude",
        workspace_path="/tmp/demo",
        session_path="/tmp/demo/session.toml",
    )


def test_send_and_verify_sent_stdout_is_delivered(monkeypatch) -> None:
    adapter = TmuxCliAdapter(agents_root=Path("/tmp/agents"))

    monkeypatch.setattr(
        adapter,
        "_send_and_verify",
        lambda _handle, _text: subprocess.CompletedProcess(
            args=["send-and-verify.sh"],
            returncode=0,
            stdout="SENT: demo-builder-claude\n",
            stderr="",
        ),
    )

    result = adapter._send_message_send_and_verify(_handle(), "hello")

    assert result.delivered is True
    assert result.transport == "send-and-verify"
    assert result.detail == "SENT: demo-builder-claude"


def test_send_and_verify_zero_exit_without_sent_or_ok_is_not_delivered(monkeypatch) -> None:
    adapter = TmuxCliAdapter(agents_root=Path("/tmp/agents"))

    monkeypatch.setattr(
        adapter,
        "_send_and_verify",
        lambda _handle, _text: subprocess.CompletedProcess(
            args=["send-and-verify.sh"],
            returncode=0,
            stdout="unexpected output\n",
            stderr="",
        ),
    )

    result = adapter._send_message_send_and_verify(_handle(), "hello")

    assert result.delivered is False
    assert "unexpected output" in result.detail


def test_send_keys_strategy_is_ignored() -> None:
    adapter = TmuxCliAdapter(agents_root=Path("/tmp/agents"))

    strategies = adapter._parse_message_strategies("send-keys,send-and-verify")

    assert strategies == ("send-and-verify",)


def test_send_and_verify_targets_project_seat_id_not_runtime_session(monkeypatch) -> None:
    adapter = TmuxCliAdapter(agents_root=Path("/tmp/agents"))
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="SENT: demo-builder-claude\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    adapter._send_and_verify(_handle(), "hello")

    assert calls[0][1:] == ["--project", "demo", "builder", "hello"]


def test_send_message_delegates_canonical_resolution_to_send_and_verify(monkeypatch) -> None:
    adapter = TmuxCliAdapter(agents_root=Path("/tmp/agents"))

    monkeypatch.setattr(adapter, "_session_exists", lambda _runtime_id: False)
    monkeypatch.setattr(
        adapter,
        "_send_and_verify",
        lambda _handle, _text: subprocess.CompletedProcess(
            args=["send-and-verify.sh"],
            returncode=0,
            stdout="SENT: demo-builder-claude\n",
            stderr="",
        ),
    )

    result = adapter.send_message(_handle(), "hello")

    assert result.delivered is True
    assert result.detail == "SENT: demo-builder-claude"
