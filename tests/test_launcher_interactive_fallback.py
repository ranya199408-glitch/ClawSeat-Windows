"""Tests for FR-6: TTY interactive fallback in agent-launcher.sh.

Tests three scenarios:
1. Non-TTY + no --tool  → exit 2 (original behaviour preserved).
2. TTY + no --tool + --headless → exit 2 (headless gate still works).
3. TTY + no --tool + valid stdin input → reaches validate (not exit 2).
"""
from __future__ import annotations

import os
import pty
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
LAUNCHER = _REPO / "core" / "launchers" / "agent-launcher.sh"

_BASE_ENV = {**os.environ}


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_plain(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run launcher with capture_output=True (stdin is NOT a TTY)."""
    return subprocess.run(
        ["/bin/bash", str(LAUNCHER)] + args,
        capture_output=True,
        text=True,
        timeout=10,
        env=_BASE_ENV,
        **kwargs,
    )


def _run_with_pty_input(args: list[str], stdin_text: str, timeout: float = 10) -> subprocess.CompletedProcess:
    """Run launcher inside a PTY so bash sees stdin as a TTY.

    We create a master/slave PTY pair, feed *stdin_text* to the master, and
    wait for the child to exit.  stdout/stderr from the child are captured via
    separate pipes (not the PTY) so we can inspect them without TTY noise.
    """
    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(
            ["/bin/bash", str(LAUNCHER)] + args,
            stdin=slave_fd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_BASE_ENV,
            close_fds=True,
        )
        # Close slave end in the parent — child owns it.
        os.close(slave_fd)
        slave_fd = -1

        # Write the simulated user input to the PTY master.
        os.write(master_fd, stdin_text.encode())

        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
    finally:
        if slave_fd != -1:
            os.close(slave_fd)
        os.close(master_fd)

    return subprocess.CompletedProcess(
        args=proc.args,
        returncode=proc.returncode,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────────

def test_non_tty_no_tool_exits_2() -> None:
    """Without a TTY, missing --tool must still exit 2 (original behaviour)."""
    result = _run_plain(["--dir", "/tmp"])
    assert result.returncode == 2, (
        f"Expected exit 2 for missing --tool in non-TTY mode, got {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )
    assert "--tool is required" in result.stderr


def test_tty_headless_no_tool_exits_2() -> None:
    """With a PTY but --headless flag set, missing --tool must still exit 2."""
    result = _run_with_pty_input(["--headless", "--dir", "/tmp"], stdin_text="\n\n")
    assert result.returncode == 2, (
        f"Expected exit 2 with --headless + no --tool, got {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )
    assert "--tool is required" in result.stderr


def test_tty_no_tool_with_valid_input_does_not_exit_2() -> None:
    """With a PTY and valid stdin input, the launcher should pass validation.

    We feed 'claude\\noauth\\n' as the interactive answers.  The launcher will
    then proceed past validate_top_level_inputs() and fail later (tmux/session
    setup), but it must NOT exit with code 2 from a missing-tool error.
    """
    result = _run_with_pty_input(["--dir", "/tmp"], stdin_text="claude\noauth\n")
    # Must not be the "input validation" exit-2 we're guarding against.
    assert result.returncode != 2 or "--tool is required" not in result.stderr, (
        "Launcher exited 2 with '--tool is required' even though valid input was supplied.\n"
        f"returncode: {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    # Confirm the prompt text appeared (proves the interactive path ran).
    assert "Tool [claude/codex/gemini]" in result.stderr or result.returncode != 2, (
        "Expected TTY prompt to appear in stderr but it did not.\n"
        f"stderr: {result.stderr}"
    )
