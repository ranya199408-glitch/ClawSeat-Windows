"""Regression tests for send-and-verify.sh input validation (audit H3).

The script runs `tmux send-keys -l` which presses every byte of the
message literally into the pane. Two surfaces exist:

- $SESSION flows into `tmux has-session` / `send-keys -t` — every
  control character (LF/CR/VT/FF) must be rejected.
- $MSG is rendered into the pane. CR would act as a bare Return
  mid-message; VT/FF would garble output; those are rejected. LF is
  intentionally allowed — the fire-and-forget design supports
  multi-line sends (see test_send_notify_simplified::test_newline_message).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "shell-scripts" / "send-and-verify.sh"

# rc=2 is reserved for INPUT_REJECTED.
REJECT_RC = 2


def _run(session: str, message: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), session, message],
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize(
    "bad_char, name",
    [
        ("\r", "CR"),
        ("\x0b", "VT"),
        ("\x0c", "FF"),
    ],
)
def test_message_with_control_char_is_rejected(bad_char: str, name: str, isolated_tasks_dir) -> None:
    result = _run("koder", f"hello{bad_char}world")
    assert result.returncode == REJECT_RC, (
        f"{name} in message should hit INPUT_REJECTED, got rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "INPUT_REJECTED" in result.stderr
    assert "HARD_BLOCK" in result.stderr


def test_message_with_LF_is_allowed() -> None:
    """Multi-line messages are a supported feature — `send-keys -l`
    transmits embedded LF bytes literally; the trailing Enter then
    submits. Validator must not reject."""
    result = _run("nonexistent-session", "line1\nline2")
    assert result.returncode != REJECT_RC, (
        f"LF in message was rejected (rc={result.returncode}); "
        f"stderr={result.stderr}"
    )


@pytest.mark.parametrize(
    "bad_char, name",
    [
        ("\n", "LF"),
        ("\r", "CR"),
        ("\x0b", "VT"),
        ("\x0c", "FF"),
    ],
)
def test_session_name_with_control_char_is_rejected(bad_char: str, name: str, isolated_tasks_dir) -> None:
    """Session names flow straight into tmux commands — every control
    char is rejected, LF included (unlike in $MSG)."""
    result = _run(f"koder{bad_char}pwned", "hi")
    assert result.returncode == REJECT_RC
    assert "INPUT_REJECTED" in result.stderr
    assert "session" in result.stderr


def test_oversized_message_is_rejected(isolated_tasks_dir) -> None:
    result = _run("koder", "x" * 9000)
    assert result.returncode == REJECT_RC
    assert "exceeds" in result.stderr


def test_usage_message_when_args_missing() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 1
    assert "Usage" in result.stdout


def test_plain_message_passes_validation_and_hits_tmux_layer() -> None:
    """A clean message clears validation. With no live tmux session the
    script will fail later (TMUX_MISSING or SESSION_NOT_FOUND) — the
    point is that it does NOT exit with the reject code."""
    result = _run("nonexistent-session", "hello world")
    assert result.returncode != REJECT_RC, (
        f"clean message was rejected as input (rc={result.returncode}); "
        f"stderr={result.stderr}"
    )


def test_resolved_session_with_control_char_is_rejected(tmp_path: Path) -> None:
    """A compromised or buggy agentctl could return a session name with
    control characters. The original $SESSION passes validation; the
    resolved name must be re-validated before it flows into tmux."""
    fake_agentctl = tmp_path / "agentctl.sh"
    fake_agentctl.write_text('#!/usr/bin/env bash\nprintf "koder\\npwned"\n')
    fake_agentctl.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT), "koder", "hi"],
        capture_output=True,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin", "AGENTCTL_BIN": str(fake_agentctl)},
    )
    assert result.returncode == REJECT_RC, (
        f"resolved control char must be rejected (rc={result.returncode})\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "resolved" in result.stderr
    assert "INPUT_REJECTED" in result.stderr
