"""Regression tests for wait-for-text.sh target validation.

`wait-for-text.sh` calls `tmux capture-pane -t "$target"`. Before the
target-format check was added, any string — including pane addresses
for unrelated sessions — would flow through, giving a caller the
ability to read content from panes they shouldn't see. The validator
locks `$target` to the tmux grammar `session[:window[.pane]]` over
`[A-Za-z0-9_-]` atoms.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "shell-scripts" / "wait-for-text.sh"


def _run(target: str, timeout: int = 1) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "-t", target, "-p", "x", "-T", str(timeout)],
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.parametrize(
    "bad_target",
    [
        "bad;session",
        "sess`whoami`",
        "a$(ls)",
        "a b",
        "a/b",
        "../../etc/passwd",
        "session\nnewline",
        "sess:win:extra",   # too many colons
        "sess:win.pane.x",  # too many dots
    ],
)
def test_invalid_target_rejected(bad_target: str) -> None:
    result = _run(bad_target)
    assert result.returncode == 1
    assert "target must match" in result.stderr


@pytest.mark.parametrize(
    "good_target",
    [
        "koder",
        "install-planner-claude",
        "install-planner-claude:0",
        "install-planner-claude:0.1",
        "A_B-1",
    ],
)
def test_valid_target_passes_validation(good_target: str) -> None:
    """Valid target may time out (no live tmux session) but must not be
    rejected by the format check."""
    result = _run(good_target)
    # rc=1 + format-error stderr means reject; timeout also returns rc=1
    # but with different stderr — we only care that it got past validation.
    assert "target must match" not in result.stderr
