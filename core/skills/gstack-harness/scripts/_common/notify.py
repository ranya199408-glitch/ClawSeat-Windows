"""Notify, pane capture, onboarding, and memory-target guard helpers."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from _feishu import send_feishu_user_message
from _utils import AGENT_HOME, run_command, run_command_with_env

from .profile import HarnessProfile
from .session import resolve_session_name, session_name_for

__all__ = [
    "CLAUDE_ONBOARDING_MARKERS",
    "notify",
    "capture_session_pane",
    "detect_claude_onboarding_step",
    "MEMORY_SEAT_NAME",
    "MEMORY_QUERY_POINTER",
    "assert_target_not_memory",
    "add_notify_args",
    "resolve_notify",
    "_should_announce_planner_event",
    "_try_announce_planner_event",
]


#
# Marker strings are verified against real CLI output. Sources of truth:
#   - claude-code 2.1.112  (inspected package bundle + live runs)
#   - codex-cli   0.121.0  (inspected bundle + live first-run in isolated HOME)
#   - gemini-cli  0.38.1   (inspected bundle + live first-run in isolated HOME)
# If you upgrade a CLI, re-verify every line below and update tests/
# test_onboarding_markers.py accordingly. Do NOT add markers based on docs
# alone — only strings you can observe in a captured pane.
CLAUDE_ONBOARDING_MARKERS: list[tuple[str, str]] = [
    # ── Claude Code ────────────────────────────────────────────────
    ("Browser didn't open? Use the url below to sign in", "claude_oauth_login"),
    ("Paste code here if prompted >", "claude_oauth_code"),
    ("Login successful. Press Enter to continue", "claude_oauth_continue"),
    ("Accessing workspace:", "claude_workspace_trust"),
    ("Quick safety check:", "claude_workspace_trust"),
    ("WARNING: Claude Code running in Bypass Permissions mode", "claude_bypass_permissions"),
    ("OAuth error:", "claude_oauth_error"),
    # ── Codex (OpenAI) CLI ────────────────────────────────────────
    # First-run auth menu, ChatGPT OAuth (device-code), API key entry, and
    # the directory-trust + approval-gate prompts.
    ("Sign in with ChatGPT", "codex_oauth_login"),
    ("Provide your own API key", "codex_api_login"),
    ("Finish signing in via your browser", "codex_oauth_login"),
    ("If the link doesn't open automatically", "codex_oauth_login"),
    ("Enter this one-time code", "codex_oauth_code"),
    ("Do you trust the contents of this directory?", "codex_workspace_trust"),
    ("Approval requested:", "codex_approval_prompt"),
    ("Approval needed in", "codex_approval_prompt"),
    # ── Gemini CLI ────────────────────────────────────────────────
    # First-run auth menu, Google OAuth wait, and the folder-trust prompt.
    # The Google account picker is a browser step — there is no TUI marker
    # for it, so we do not try to detect it.
    ("Sign in with Google", "gemini_oauth_menu"),
    ("Waiting for authentication", "gemini_oauth_login"),
    ("Do you trust the files in this folder?", "gemini_workspace_trust"),
]


def notify(profile: HarnessProfile, target_seat: str, message: str) -> subprocess.CompletedProcess[str]:
    session_name = resolve_session_name(profile, target_seat)
    # C6: always thread --project so multi-project installs don't let
    # send-and-verify.sh fall through to agentctl's unscoped session-name
    # lookup (which would pick any project with a matching seat id and
    # silently deliver to the wrong tmux window).
    # run_command_with_env already passes os.environ.copy(); HOME override anchors
    # the per-project tasks root. AGENT_LAUNCHER_TMUX_SEND_ACTIVE bypasses the
    # agent-launcher tmux guard on the raw send-keys fallback path in
    # send-and-verify.sh — harmless when the tmux-send delegate path is taken.
    return run_command_with_env(
        [str(profile.send_script), "--project", profile.project_name, session_name, message],
        cwd=profile.repo_root,
        env={"HOME": str(AGENT_HOME), "AGENT_LAUNCHER_TMUX_SEND_ACTIVE": "1"},
    )

def capture_session_pane(profile: HarnessProfile, seat: str, *, lines: int = 160) -> str:
    session_name = session_name_for(profile, seat)
    if not session_name:
        return ""
    result = run_command(
        ["tmux", "capture-pane", "-t", session_name, "-p"],
        cwd=profile.repo_root,
    )
    if result.returncode != 0:
        return ""
    pane_text = result.stdout
    if not pane_text:
        return ""
    return "\n".join(pane_text.splitlines()[-lines:])


def detect_claude_onboarding_step(pane_text: str) -> str | None:
    for marker, step in CLAUDE_ONBOARDING_MARKERS:
        if marker in pane_text:
            return step
    return None

# notification to memory therefore fails silently: by the time the
# notify text lands in the tmux pane, memory has already /clear'd and
# cannot see the TODO queue. Callers must instead use the read-only
# query_memory.py tool, which writes a prompt file the UserPromptSubmit
# hook can inject a fresh context for.
#
# This guard lives in _common.py so both dispatch_task.py and
# notify_seat.py pick it up from the same import surface they already
# use. See core/skills/clawseat-install/references/memory-query-protocol.md
# for the full seat→memory contract.

MEMORY_SEAT_NAME = "memory"

MEMORY_QUERY_POINTER = (
    "To interact with memory, use the read-only query tool:\n"
    "  python3 $CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py \\\n"
    "    --ask \"<question>\" --profile <profile>\n"
    "\n"
    "Or for a direct key / file lookup:\n"
    "  python3 $CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py \\\n"
    "    --key <dot.path>\n"
    "  python3 $CLAWSEAT_ROOT/core/skills/memory-oracle/scripts/query_memory.py \\\n"
    "    --file <file-stem> --section <section>\n"
    "\n"
    "See core/skills/clawseat-install/references/memory-query-protocol.md"
)


def assert_target_not_memory(target: str, caller_tool: str) -> None:
    """Exit 2 if ``target`` is the memory seat.

    Both dispatch_task.py and notify_seat.py call this after argparse,
    before writing any TODO / receipt / tmux notification. The exit code
    mirrors argparse's own exit code for bad invocations so scripted
    callers can treat "bad target" and "bad flag" uniformly.

    T22 (folded into T19 PR-2 for merge convenience):
    notify_seat.py is allowed to target memory because T7 memory-query-protocol
    Missing-Key Escalation requires it — memory needs to receive notification
    when a key it asked for is missing. dispatch_task.py + dynamic variants
    remain blocked because memory doesn't read TODO.md entries.
    """
    import sys as _sys

    if target == MEMORY_SEAT_NAME and caller_tool != "notify_seat.py":
        print(
            f"error: {caller_tool} does not support --target memory.\n"
            "       Memory is a synchronous oracle; dispatching writes TODO\n"
            "       entries the target cannot read because its context is\n"
            "       cleared between turns (/clear Stop hook).\n"
            "\n"
            f"{MEMORY_QUERY_POINTER}",
            file=_sys.stderr,
        )
        raise SystemExit(2)


def add_notify_args(parser: "argparse.ArgumentParser") -> None:
    """Add --notify / --no-notify / --skip-notify (deprecated) to *parser*.

    C15: notify is default-ON. --no-notify opts out. --skip-notify is the
    legacy alias kept for backwards compatibility (logs a deprecation warning).
    Call this helper from both static and dynamic dispatch/handoff scripts so
    the semantics stay in sync via BASE_COMMON re-export.
    """
    import argparse as _argparse  # noqa: F401 — only needed for the type hint above
    notify_group = parser.add_mutually_exclusive_group()
    notify_group.add_argument(
        "--notify", action="store_true", default=None,
        help="Send tmux notify to target after dispatch/completion (default).",
    )
    notify_group.add_argument(
        "--no-notify", action="store_true",
        help="Suppress tmux notify. Target must discover the task by reading its queue/DELIVERY.md.",
    )
    # Legacy alias — accepted but logs deprecation warning to stderr.
    parser.add_argument(
        "--skip-notify", action="store_true",
        help="[deprecated] Use --no-notify. Kept for backwards compatibility.",
    )


def resolve_notify(args: "argparse.Namespace") -> bool:
    """Resolve the effective notify flag from parsed args.

    Returns True (notify) by default; False when --no-notify or --skip-notify given.
    Prints a deprecation warning to stderr when --skip-notify is used.
    """
    import sys as _sys
    do_notify = True
    if getattr(args, "no_notify", False) or getattr(args, "skip_notify", False):
        do_notify = False
    if getattr(args, "skip_notify", False):
        print("warn: --skip-notify is deprecated; use --no-notify", file=_sys.stderr)
    return do_notify

def _should_announce_planner_event(source: str, target: str, profile=None) -> bool:
    override = os.environ.get("CLAWSEAT_ANNOUNCE_PLANNER_EVENTS")
    if override is not None:
        return override == "1" and (source == "planner" or target == "planner")
    observability = getattr(profile, "observability", None)
    if observability is None:
        return False
    return getattr(observability, "announce_planner_events", False) and (
        source == "planner" or target == "planner"
    )


def _try_announce_planner_event(*, project: str, source: str, target: str, task_id: str, verb: str) -> dict:
    message = f"[{project}] {source} → {target}: {task_id} {verb}"
    if len(message) > 80:
        message = message[:77] + "..."
    try:
        from _feishu import send_feishu_user_message
        result = send_feishu_user_message(message, project=project)
    except Exception as exc:
        print(f"warn: planner announce failed for {task_id}: {exc}", file=sys.stderr)
        return {"status": "exception", "reason": str(exc)}
    result = result or {}
    if result.get("status") not in ("sent", "skipped"):
        detail = result.get("stderr") or result.get("stdout") or result.get("reason", "unknown")
        print(f"warn: planner announce feishu returned {result.get('status')!r} for {task_id}: {detail}", file=sys.stderr)
    return result
