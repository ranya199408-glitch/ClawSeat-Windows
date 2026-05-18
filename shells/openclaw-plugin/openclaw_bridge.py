#!/usr/bin/env python3
"""
OpenClaw koder -> ClawSeat control bridge (production version).

Bridges OpenClaw koder to ClawSeat control plane, allowing OpenClaw to:
- View team seat status
- Dispatch tasks to planner
- Instantiate new seats via TmuxCliAdapter
- Read planner state (brief, pending frontstage)
- Switch projects

Three-layer relationship:
  OpenClaw koder (user entry + agent orchestration)
       | calls ClawSeat adapter
  ClawSeat control plane (seat management + protocol + roster)
       | calls TmuxCliAdapter
  tmux engineer team (claude-code / codex / gemini sessions)

No core protocol logic lives here -- this is only OpenClaw -> ClawSeat adapter
call wrapping.

Production path: ClawSeat/shells/openclaw-plugin/openclaw_bridge.py
Uses canonical imports from ClawSeat core/ and adapters/.

Module structure (split for maintainability):
  openclaw_bridge.py   -- bootstrap / safe_start / exceptions + re-exports
  _bridge_binding.py   -- project binding / group management
  _bridge_adapters.py  -- adapter init / tmux loading / profile
  _bridge_seats.py     -- seat operations / dispatch / planner state
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any

# Resolve CLAWSEAT_ROOT via shared core/resolve.py
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT_BRIDGE = _SCRIPT_DIR.parents[1]  # shells/openclaw-plugin/ -> shells/ -> ClawSeat root
_core_path = str(_REPO_ROOT_BRIDGE / "core")
if _core_path not in sys.path:
    sys.path.insert(0, _core_path)
from resolve import resolve_clawseat_root as _resolve_clawseat_root

_CLAWSEAT_ROOT = _resolve_clawseat_root()
_BRIDGE_BINDING_LOCK = threading.RLock()

# Add ClawSeat root to sys.path for canonical imports
if str(_CLAWSEAT_ROOT) not in sys.path:
    sys.path.insert(0, str(_CLAWSEAT_ROOT))
from core.lib.real_home import real_user_home

# Canonical imports from ClawSeat core/
from core.adapter.clawseat_adapter import (
    AdapterResult,
    BriefState,
    ClawseatAdapter,
    PendingFrontstageItem,
    SessionStatus,
)

# ---------------------------------------------------------------------------
# Re-exports from split modules (backward compatibility)
# ---------------------------------------------------------------------------

# Group 1: Project binding / group management
from _bridge_binding import (  # noqa: F401, E402
    _bridge_now_iso,
    _bridge_path_for_project,
    _collect_project_bindings,
    _load_bridge_file,
    _projects_root,
    _quote_toml,
    _write_bridge_file,
    bind_project_to_group,
    get_binding_for_group,
    list_project_bindings,
    unbind_project,
)

# Group 2: Adapter init / tmux loading
from _bridge_adapters import (  # noqa: F401, E402
    _get_tmux_adapter_module,
    _load_tmux_adapter,
    ensure_clawseat_profile,
    init_clawseat_adapter,
    init_tmux_adapter,
)

# Group 3: Seat operations
from _bridge_seats import (  # noqa: F401, E402
    check_seat_status,
    dispatch_task_to_planner,
    get_team_summary,
    instantiate_seat,
    list_team_sessions,
    probe_seat_state,
    probe_seat_state_detailed,
    read_pending_frontstage,
    read_planner_brief,
    resume_seat_if_needed,
    start_seat_via_tmux,
    switch_project,
)


# ---------------------------------------------------------------------------
# Safe seat start with preflight (Group 4 -- stays in this file)
# ---------------------------------------------------------------------------


class EnvironmentNotReady(Exception):
    """Raised when preflight checks reveal hard blocks."""

    def __init__(self, items: list[Any]) -> None:
        self.items = items
        details = []
        for i in items:
            line = f"  [{i.name}] {getattr(i, 'message', '')}"
            fix = getattr(i, "fix_command", None)
            if fix:
                line += f"\n    fix: {fix}"
            details.append(line)
        summary = "\n".join(details)
        super().__init__(f"environment not ready ({len(items)} issue(s)):\n{summary}")


class CLINotAvailable(Exception):
    """Raised when the required CLI tool is not available."""

    def __init__(self, template_id: str, instructions: str) -> None:
        self.template_id = template_id
        self.instructions = instructions
        super().__init__(f"{template_id} CLI not available: {instructions}")


class AuthNotConfigured(Exception):
    """Raised when auth credentials are missing for a seat."""

    def __init__(self, seat_id: str, path: str, instructions: str) -> None:
        self.seat_id = seat_id
        self.path = path
        self.instructions = instructions
        super().__init__(f"auth not configured for {seat_id}: {instructions}")


def _run_preflight(project_name: str) -> None:
    """Run preflight checks with auto-fix retry. Raises EnvironmentNotReady on failure."""
    from core import preflight

    result = preflight.preflight_check(project_name)
    if result.has_hard_blocked:
        raise EnvironmentNotReady(result.hard_blocked_items)

    for item in result.retryable_items:
        preflight.auto_fix(item, project_name)

    result = preflight.preflight_check(project_name)
    if not result.all_pass:
        raise EnvironmentNotReady(result.hard_blocked_items + result.retryable_items)


_CLI_MAP: dict[str, tuple[str, str]] = {
    "claude": ("claude", "npm install -g @anthropic-ai/claude-code"),
    "codex": ("codex", "npm install -g @anthropic-ai/codex"),
    "gemini": ("gemini", "pip install google-generativeai && set API_KEY in secrets"),
}


def _check_cli_available(template_id: str) -> None:
    """Verify the tool CLI is installed. Raises CLINotAvailable if missing."""
    import shutil as _sh

    cli_name, install_hint = _CLI_MAP.get(template_id, (template_id, f"install {template_id}"))
    if not _sh.which(cli_name):
        raise CLINotAvailable(
            template_id,
            f"CLI {cli_name!r} not found in PATH. Install: {install_hint}",
        )


_TOOL_SECRET_TEMPLATES: dict[str, str] = {
    "claude": "~/.agents/secrets/claude/anthropic/{project}/{seat}.env",
    "codex": "~/.agents/secrets/codex/openai/{project}/{seat}.env",
    "gemini": "~/.agents/secrets/gemini/google/{project}/{seat}.env",
}


def _check_auth(project_name: str, seat_id: str, template_id: str) -> None:
    """Verify seat auth credentials exist. Raises AuthNotConfigured if missing."""
    try:
        import tomllib as _tomllib
    except ModuleNotFoundError:
        import tomli as _tomllib  # type: ignore

    session_path = (
        Path(os.environ.get("SESSIONS_ROOT", str(real_user_home() / ".agents" / "sessions")))
        / project_name / seat_id / "session.toml"
    )

    # Try session binding first
    if session_path.exists():
        try:
            with session_path.open("rb") as f:
                binding = _tomllib.load(f)
            secret_file = binding.get("secret_file", "")
            if secret_file:
                sf = Path(secret_file).expanduser()
                if not sf.exists():
                    raise AuthNotConfigured(
                        seat_id, secret_file,
                        f"Secret file does not exist: {sf}. Create it and add your API key.",
                    )
                if sf.read_text().strip() == "":
                    raise AuthNotConfigured(
                        seat_id, secret_file,
                        f"Secret file is empty: {sf}. Add your API key.",
                    )
                return  # auth OK via session binding
        except (OSError, KeyError, ValueError) as exc:
            print(f"warning: could not read session binding {session_path}: {exc}", file=sys.stderr)

    # Fallback: tool-specific default secret path
    tpl = _TOOL_SECRET_TEMPLATES.get(template_id, "~/.agents/secrets/unknown/{seat}.env")
    default_secret = Path(tpl.format(project=project_name, seat=seat_id)).expanduser()
    if not default_secret.exists():
        raise AuthNotConfigured(
            seat_id, str(default_secret),
            f"No auth configured for {template_id} seat {seat_id}. "
            f"Create {default_secret} with your API key.",
        )


def safe_start_seat(
    project_name: str,
    seat_id: str,
    template_id: str,
    *,
    clawseat_adapter: ClawseatAdapter | None = None,
    tmux_adapter: Any | None = None,
) -> dict[str, Any]:
    """
    Safely start a seat after running preflight checks.

    Raises EnvironmentNotReady, CLINotAvailable, or AuthNotConfigured on failure.
    Returns the session handle on success.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()

    _run_preflight(project_name)
    _check_cli_available(template_id)
    _check_auth(project_name, seat_id, template_id)

    return start_seat_via_tmux(
        seat_id=seat_id,
        project_name=project_name,
        tmux_adapter=tmux_adapter,
        clawseat_adapter=clawseat_adapter,
    )


# ---------------------------------------------------------------------------
# Bootstrap entrypoint
# ---------------------------------------------------------------------------


def bootstrap(
    project_name: str = "install",
    *,
    profile_path: str | Path | None = None,
    skip_preflight: bool = False,
) -> dict[str, Any]:
    """
    Bootstrap the OpenClaw -> ClawSeat bridge.

    Runs preflight_check first; auto-fixes retryable items and re-checks.
    Writes BOOTSTRAP_RECEIPT.toml on success. Skips preflight if a valid
    receipt already exists (unless skip_preflight=True).

    Raises EnvironmentNotReady if hard_blocked items prevent bootstrap.
    """
    from core import preflight as _preflight

    # bootstrap_receipt imports tomllib -- defer until after preflight to avoid
    # crashing before we can report HARD_BLOCKED in Python < 3.11 without tomli.
    _bootstrap_receipt: Any = None
    try:
        from core import bootstrap_receipt as _bootstrap_receipt_module
        _bootstrap_receipt = _bootstrap_receipt_module
    except ImportError:
        # tomllib unavailable and tomli not installed -- will surface as HARD_BLOCKED
        pass

    preflight_result: _preflight.PreflightResult | None = None
    receipt_valid = False

    if not skip_preflight:
        # Check existing receipt if bootstrap_receipt module loaded successfully
        if _bootstrap_receipt is not None:
            existing = _bootstrap_receipt.read_receipt(project_name)
            if existing is not None:
                valid, _reason = _bootstrap_receipt.is_valid(existing)
                if valid:
                    receipt_valid = True
                else:
                    preflight_result = _preflight.preflight_check(project_name)
            else:
                preflight_result = _preflight.preflight_check(project_name)
        else:
            # bootstrap_receipt unavailable -- run preflight to surface the tomllib HARD_BLOCKED
            preflight_result = _preflight.preflight_check(project_name)

    if preflight_result is not None:
        if preflight_result.has_hard_blocked:
            raise EnvironmentNotReady(preflight_result.hard_blocked_items)

        # Auto-fix retryable items and re-check
        if preflight_result.has_retryable:
            for item in preflight_result.retryable_items:
                fixed = _preflight.auto_fix(item, project_name)
                idx = preflight_result.items.index(item)
                preflight_result.items[idx] = fixed
            # Re-run full preflight to confirm
            preflight_result = _preflight.preflight_check(project_name)
            if not preflight_result.all_pass:
                raise EnvironmentNotReady(
                    preflight_result.hard_blocked_items + preflight_result.retryable_items
                )

        # Write receipt on success (only when we ran fresh preflight)
        if preflight_result is not None and _bootstrap_receipt is not None:
            _bootstrap_receipt.write_receipt(project_name, preflight_result)

    clawseat_adapter = init_clawseat_adapter(project_name=project_name, profile_path=profile_path)

    tmux_adapter = init_tmux_adapter()

    switch_result = clawseat_adapter.switch_project(project_name=project_name)

    brief = clawseat_adapter.read_brief(project_name=project_name)

    pending_items = clawseat_adapter.read_pending_frontstage(project_name=project_name)

    return {
        "project_name": project_name,
        "profile_path": switch_result["profile_path"],
        "current_project": clawseat_adapter.current_project,
        "frontstage_epoch": clawseat_adapter.frontstage_epoch,
        "clawseat_adapter": "initialized",
        "tmux_adapter": type(tmux_adapter).__name__,
        "planner_brief_title": brief.title,
        "planner_brief_status": brief.status,
        "planner_brief_disposition": brief.frontstage_disposition,
        "pending_frontstage_count": len(pending_items),
    }


__all__ = [
    "AuthNotConfigured",
    "bind_project_to_group",
    "bootstrap",
    "check_seat_status",
    "CLINotAvailable",
    "dispatch_task_to_planner",
    "ensure_clawseat_profile",
    "EnvironmentNotReady",
    "get_binding_for_group",
    "get_team_summary",
    "init_clawseat_adapter",
    "init_tmux_adapter",
    "instantiate_seat",
    "list_project_bindings",
    "list_team_sessions",
    "probe_seat_state",
    "probe_seat_state_detailed",
    "read_pending_frontstage",
    "read_planner_brief",
    "resume_seat_if_needed",
    "safe_start_seat",
    "start_seat_via_tmux",
    "switch_project",
    "unbind_project",
]
