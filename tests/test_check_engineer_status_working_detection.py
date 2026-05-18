"""Pin tests for check-engineer-status.sh section 2.5 working-state detection.

Root cause: while Claude/Codex/Gemini execute tools the bottom of their pane
shows an idle prompt (❯ / › / "Type your message"). The old detector reached
the idle-prompt section first and emitted IDLE/STALLED. Section 2.5 intercepts
these cases before the idle-prompt checks fire.

Test strategy: create a fake `tmux` shim that outputs controlled pane content
and a controlled pane meta line, then call check-engineer-status.sh against it.
Also create a minimal TASKS_ROOT so mailbox checks return a known state (EMPTY).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "shell-scripts" / "check-engineer-status.sh"
_AGENTCTL = _REPO / "core" / "shell-scripts" / "agentctl.sh"


def _run_status(
    tmp_path: Path,
    pane_content: str,
    pane_title: str = "builder",
    pane_cmd: str = "claude",
    seat: str = "builder",
    has_todo: bool = False,
) -> str:
    """Run check-engineer-status.sh with a synthetic pane and return its stdout."""
    # Fake tmux binary: returns pane_content for capture-pane, meta for display-message.
    fake_tmux = tmp_path / "bin" / "tmux"
    fake_tmux.parent.mkdir(parents=True, exist_ok=True)
    # Escape pane_content carefully for the shell script.
    # We write it to a file and cat it so no quoting issues with special chars.
    pane_file = tmp_path / "pane.txt"
    pane_file.write_text(pane_content, encoding="utf-8")
    meta_line = f"{pane_cmd}|{pane_title}"
    fake_tmux.write_text(
        textwrap.dedent(f"""\
            #!/bin/bash
            # Fake tmux for testing check-engineer-status.sh
            case "$1" in
              capture-pane) cat '{pane_file}' ;;
              display-message) printf '%s\\n' '{meta_line}' ;;
              has-session) exit 0 ;;
              *) exit 0 ;;
            esac
        """),
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)

    # Fake agentctl: just echo the last arg as session name.
    fake_agentctl = tmp_path / "bin" / "agentctl.sh"
    fake_agentctl.write_text(
        textwrap.dedent(f"""\
            #!/bin/bash
            # echo seat id as session name
            echo '{seat}'
        """),
        encoding="utf-8",
    )
    fake_agentctl.chmod(0o755)

    # Minimal TASKS_ROOT so mailbox returns EMPTY (no TODO/DELIVERY files).
    tasks_root = tmp_path / "tasks"
    (tasks_root / seat).mkdir(parents=True, exist_ok=True)
    if has_todo:
        (tasks_root / seat / "TODO.md").write_text(
            "task_id: TEST-001\ntitle: test\n", encoding="utf-8"
        )

    env = {
        **os.environ,
        "PATH": f"{fake_tmux.parent}:{os.environ['PATH']}",
        "TASKS_ROOT": str(tasks_root),
        "DEFAULT_SESSIONS": seat,
        # Prevent the script from trying to resolve AGENT_PROJECT from env
        "AGENT_PROJECT": "",
        # Point AGENTCTL at our fake
        "AGENTCTL": str(fake_agentctl),
    }

    result = subprocess.run(
        ["bash", str(_SCRIPT), seat],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result.stdout.strip()


# ── Claude Code misdetection scenarios ───────────────────────────────────────


def test_claude_tool_bullet_not_idle(tmp_path: Path) -> None:
    """⏺ tool bullet in pane body → WORKING, not IDLE even with ❯ at bottom."""
    pane = (
        "⏺ Bash(ls -la /tmp)\n"
        "  total 0\n"
        "  drwxr-xr-x  2 user  staff  64 Jan  1 00:00 .\n"
        "\n"
        "❯ \n"
    )
    out = _run_status(tmp_path, pane, pane_title="builder", pane_cmd="claude")
    assert out.startswith(f"builder: WORKING"), (
        f"⏺ bullet should trigger WORKING before ❯ fires IDLE; got: {out!r}"
    )


def test_claude_cc_spinner_not_idle(tmp_path: Path) -> None:
    """✶ / ✻ / ✢ spinner chars → WORKING, not IDLE even with ❯ at bottom."""
    for spinner in ("✶", "✻", "✢", "✳", "✽"):
        pane = f"Claude is thinking {spinner}\n\n❯ \n"
        out = _run_status(
            tmp_path / spinner, pane, pane_title="builder", pane_cmd="claude"
        )
        assert out.startswith("builder: WORKING"), (
            f"spinner {spinner!r} should trigger WORKING; got: {out!r}"
        )


def test_claude_esc_in_tail20_not_tail10(tmp_path: Path) -> None:
    """esc to interrupt pushed beyond tail-10 by long output still catches WORKING."""
    # Fill 12 lines of bash output, then esc to interrupt at line 13, then ❯
    long_output = "\n".join(f"line {i}: some bash output" for i in range(12))
    pane = long_output + "\nesc to interrupt\n" + "\n" * 3 + "❯ \n"
    out = _run_status(tmp_path, pane, pane_title="builder", pane_cmd="claude")
    assert out.startswith("builder: WORKING"), (
        f"esc to interrupt in tail-20 (beyond tail-10) should detect WORKING; got: {out!r}"
    )


# ── Codex misdetection scenarios ──────────────────────────────────────────────


def test_codex_tool_box_not_idle(tmp_path: Path) -> None:
    """│ tool output box → WORKING (codex tool), not IDLE/STALLED even with › at bottom."""
    pane = (
        "Running: bash -c 'pytest tests/ -q'\n"
        "│ collecting ...\n"
        "│ 42 passed in 3.14s\n"
        "\n"
        "› \n"
    )
    out = _run_status(tmp_path, pane, pane_title="builder", pane_cmd="codex")
    assert out.startswith("builder: WORKING"), (
        f"Codex │ tool box should trigger WORKING before › fires IDLE; got: {out!r}"
    )


def test_codex_idle_without_tool_box(tmp_path: Path) -> None:
    """Codex with just › at bottom and no tool indicators → IDLE (not a regression)."""
    pane = "Previous output\n\n› \n"
    out = _run_status(tmp_path, pane, pane_title="builder", pane_cmd="codex")
    assert "IDLE" in out or "DELIVERED" in out or "STALLED" in out, (
        f"Codex with only › and no tool indicators should be IDLE/DELIVERED/STALLED; got: {out!r}"
    )


# ── Gemini misdetection scenarios ─────────────────────────────────────────────


def test_gemini_generating_not_idle(tmp_path: Path) -> None:
    """'Generating...' in pane → WORKING (gemini active), not IDLE."""
    pane = (
        "## Chapter 3\n\n"
        "Generating...\n"
        "\n"
        "Type your message\n"
    )
    out = _run_status(tmp_path, pane, pane_title="designer", pane_cmd="gemini", seat="designer")
    assert out.startswith("designer: WORKING"), (
        f"Gemini 'Generating...' should trigger WORKING before 'Type your message' fires IDLE; got: {out!r}"
    )


def test_gemini_idle_without_active_text(tmp_path: Path) -> None:
    """Gemini with just 'Type your message' and no active text → IDLE (not a regression)."""
    pane = "Previous response.\n\nType your message\n"
    out = _run_status(tmp_path, pane, pane_title="designer", pane_cmd="gemini", seat="designer")
    assert "IDLE" in out or "DELIVERED" in out or "STALLED" in out, (
        f"Gemini with only 'Type your message' should be IDLE/DELIVERED/STALLED; got: {out!r}"
    )


# ── Regression: normal idle cases still work ─────────────────────────────────


def test_claude_clean_idle_still_idle(tmp_path: Path) -> None:
    """Clean Claude pane with just ❯ and no tool indicators → IDLE (no regression)."""
    pane = "Some completed output.\n\n❯ \n"
    out = _run_status(tmp_path, pane, pane_title="builder", pane_cmd="claude")
    assert "IDLE" in out or "DELIVERED" in out or "STALLED" in out, (
        f"Clean Claude idle pane should be IDLE/DELIVERED/STALLED; got: {out!r}"
    )
