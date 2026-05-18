#!/usr/bin/env python3
"""Windows-compatible window manager for ClawSeat.

Replaces macOS-specific iTerm2/AppleScript with WezTerm CLI.
Provides the same interface as agent_admin_window.py but for Windows.
"""

from __future__ import annotations

import json
import os
import platform
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Import shared utilities from the original module
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = str(_REPO_ROOT / "core" / "lib")
if _CORE_LIB not in sys.path:
    sys.path.insert(0, _CORE_LIB)

from tmux import tmux_session_alive as _tmux_session_alive_shared

# Import original module for shared functions
sys.path.insert(0, str(_REPO_ROOT / "core" / "scripts"))
import agent_admin_window as _original


class AgentAdminWindowError(Exception):
    pass


class SeatNotFoundInWindow(AgentAdminWindowError):
    pass


# Constants
TMUX_COMMAND_RETRIES = 2
TMUX_COMMAND_TIMEOUT_SECONDS = 8.0
TMUX_COMMAND_RETRY_DELAY_SECONDS = 1.0
_GRID_WINDOW_TITLE_PREFIX = "clawseat-"
_MEMORIES_WINDOW_TITLE = "clawseat-memories"
_MAX_PANES = 8

# WezTerm driver path
_WEZTERM_PANES_DRIVER = Path(__file__).resolve().with_name("wezterm_panes_driver.py")
_WAIT_FOR_SEAT_SCRIPT = _REPO_ROOT / "scripts" / "wait-for-seat.sh"

# Primary seat IDs
_PRIMARY_SEAT_IDS = frozenset({"ancestor", "memory"})


def _project_primary_seat_id(project: Any) -> str:
    """Return the project's primary seat id."""
    for raw_engineer_id in getattr(project, "engineers", []) or []:
        engineer_id = str(raw_engineer_id)
        if engineer_id in _PRIMARY_SEAT_IDS:
            return engineer_id
    return "memory"


def tmux(args: list[str], check: bool = True, capture_output: bool = False,
         text: bool = True, timeout: float = TMUX_COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Run tmux command."""
    cmd = ["tmux", *args]
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text, timeout=timeout)


def tmux_with_retry(args: list[str], *, label: str, check: bool = True,
                    retries: int = TMUX_COMMAND_RETRIES,
                    timeout: float = TMUX_COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Run tmux command with retry."""
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return tmux(args, check=check, capture_output=True, text=True, timeout=timeout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt >= retries:
                break
            print(f"tmux_retry: {label} attempt={attempt}/{retries} failed: {exc!s}", file=sys.stderr)
            time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)
    raise AgentAdminWindowError(f"{label} failed after {retries} attempts")


def tmux_has_session(session: str) -> bool:
    """Check if tmux session exists."""
    return _tmux_session_alive_shared(session, timeout=TMUX_COMMAND_TIMEOUT_SECONDS)


def monitor_attach_command(session: str) -> str:
    """Build attach command for monitor."""
    quoted = shlex.quote(session)
    return f"exec env -u TMUX tmux attach -t {quoted} || exec $SHELL -l"


def _tmux_attach_command(target: str) -> str:
    return f"tmux attach -t {shlex.quote('=' + target)}"


def build_attach_command(*, session: str, workspace: str, fallback_to_shell: bool = True) -> str:
    """Build deterministic attach command."""
    attach_target = shlex.quote(session)
    workspace_dir = shlex.quote(workspace)
    fallback = " || exec $SHELL -l" if fallback_to_shell else ""
    return f"cd {workspace_dir} && exec env -u TMUX tmux attach -t {attach_target}{fallback}"


def shell_attach_command(session: Any) -> str:
    """Get shell attach command for session."""
    return build_attach_command(session=session.session, workspace=session.workspace)


def project_monitor_shell_command(project: Any) -> str:
    """Get monitor shell command for project."""
    return build_attach_command(session=project.monitor_session, workspace=project.repo_root)


def _is_frontstage_engineer(engineer_id: str) -> bool:
    """Check if engineer is frontstage."""
    return engineer_id in {"koder", "frontstage"}


def _project_grid_seat_ids(project: Any) -> list[str]:
    """Return non-primary project seats."""
    roster: list[str] = []
    seen: set[str] = set()
    for raw_engineer_id in getattr(project, "engineers", []) or []:
        engineer_id = str(raw_engineer_id)
        if engineer_id in _PRIMARY_SEAT_IDS or _is_frontstage_engineer(engineer_id):
            continue
        if engineer_id in seen:
            continue
        seen.add(engineer_id)
        roster.append(engineer_id)
    return roster


def build_grid_payload(project: Any, *, wait_for_seat_script: Path | None = None) -> dict[str, Any]:
    """Build grid payload for workers window."""
    wait_script = wait_for_seat_script or _WAIT_FOR_SEAT_SCRIPT
    seats = _project_grid_seat_ids(project)
    primary_seat_id = _project_primary_seat_id(project)
    if not seats:
        print(f"agent_admin_window: project {project.name} has no worker seats; "
              f"falling back to {primary_seat_id}-only grid", file=sys.stderr)

    panes: list[dict[str, str]] = [
        {
            "label": primary_seat_id,
            "command": _tmux_attach_command(f"{project.name}-{primary_seat_id}"),
        }
    ]
    for seat_id in seats:
        panes.append({
            "label": seat_id,
            "command": (
                "bash "
                + shlex.quote(str(wait_script))
                + " "
                + shlex.quote(project.name)
                + " "
                + shlex.quote(seat_id)
            ),
        })
    return {"title": f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}", "panes": panes}


def _worker_attach_pane(*, project_name: str, seat_id: str, wait_script: Path) -> dict[str, str]:
    """Build worker attach pane spec."""
    return {
        "label": seat_id,
        "command": (
            "bash "
            + shlex.quote(str(wait_script))
            + " "
            + shlex.quote(project_name)
            + " "
            + shlex.quote(seat_id)
        ),
    }


def _workers_recipe(n_total: int) -> list[list[object]]:
    """Build workers layout recipe."""
    if n_total < 1:
        return []
    if n_total == 4:
        return [[0, True], [0, False], [1, False]]
    n_right = n_total - 1
    if n_right == 0:
        return []
    recipe: list[list[object]] = [[0, True]]
    if n_right == 1:
        return recipe
    if n_right == 2:
        recipe.append([1, False])
        return recipe

    cols = (n_right + 1) // 2
    for col in range(1, cols):
        recipe.append([col, True])
    cols_with_bottom = n_right - cols
    for col in range(cols_with_bottom):
        recipe.append([col + 1, False])
    return recipe


def _right_worker_order(n_right: int) -> list[int]:
    """Get right worker ordering."""
    if n_right <= 0:
        return []
    if n_right == 1:
        return [0]
    if n_right == 2:
        return [0, 1]

    cols = (n_right + 1) // 2
    ordering: list[int] = []
    for col in range(cols):
        user_idx = col * 2
        if user_idx < n_right:
            ordering.append(user_idx)
    for col in range(cols):
        user_idx = col * 2 + 1
        if user_idx < n_right:
            ordering.append(user_idx)
    return ordering


def build_workers_payload(project: Any, *, wait_for_seat_script: Path | None = None) -> dict[str, Any]:
    """Build workers window payload."""
    wait_script = wait_for_seat_script or _WAIT_FOR_SEAT_SCRIPT
    workers = _project_grid_seat_ids(project)
    if "planner" in workers:
        workers = ["planner", *[seat_id for seat_id in workers if seat_id != "planner"]]
    if not workers:
        raise AgentAdminWindowError(f"project {project.name} has no worker seats")
    if len(workers) > _MAX_PANES:
        raise AgentAdminWindowError(
            f"project {project.name} has {len(workers)} worker seats; "
            f"workers window supports at most {_MAX_PANES} panes"
        )

    if len(workers) == 4:
        panes = [
            _worker_attach_pane(project_name=project.name, seat_id=seat_id, wait_script=wait_script)
            for seat_id in workers
        ]
    else:
        main_worker = workers[0]
        right_workers = workers[1:]
        panes = [
            _worker_attach_pane(project_name=project.name, seat_id=main_worker, wait_script=wait_script)
        ]
        for worker_idx in _right_worker_order(len(right_workers)):
            panes.append(
                _worker_attach_pane(
                    project_name=project.name,
                    seat_id=right_workers[worker_idx],
                    wait_script=wait_script,
                )
            )
    return {
        "title": f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}-workers",
        "panes": panes,
        "recipe": _workers_recipe(len(panes)),
    }


def _tmux_session_names() -> list[str]:
    """Get list of tmux session names."""
    env = os.environ.copy()
    env.pop("TMUX", None)
    result = subprocess.run(
        ["tmux", "ls", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=TMUX_COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def build_memories_payload(project: Any) -> dict[str, Any] | None:
    """Build memories window payload."""
    del project
    live_sessions = set(_tmux_session_names())

    # Import projects_registry dynamically
    try:
        import projects_registry
        tabs = [
            {
                "name": entry.name,
                "command": _tmux_attach_command(entry.tmux_name),
            }
            for entry in projects_registry.enumerate_projects()
            if entry.name and entry.tmux_name and entry.tmux_name in live_sessions
        ]
    except ImportError:
        tabs = []

    if not tabs:
        memory_sessions = sorted(
            session for session in live_sessions if session.endswith("-memory")
        )
        tabs = [
            {
                "name": session[: -len("-memory")],
                "command": _tmux_attach_command(session),
            }
            for session in memory_sessions
        ]
    if not tabs:
        return None
    return {
        "mode": "tabs",
        "title": _MEMORIES_WINDOW_TITLE,
        "tabs": tabs,
        "ensure": True,
    }


def run_wezterm_panes_driver(payload: dict[str, Any]) -> dict[str, Any]:
    """Run WezTerm panes driver."""
    result = subprocess.run(
        [sys.executable, str(_WEZTERM_PANES_DRIVER)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"rc={result.returncode}"
        raise AgentAdminWindowError(f"WezTerm pane driver failed: {detail}")
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AgentAdminWindowError(
            f"WezTerm pane driver returned invalid JSON: {exc}: {stdout}"
        ) from exc
    if not isinstance(decoded, dict):
        raise AgentAdminWindowError("WezTerm pane driver returned a non-object payload")
    if decoded.get("status") != "ok":
        raise AgentAdminWindowError(decoded.get("reason") or "WezTerm pane driver returned non-ok status")
    return decoded


def ensure_memories_pane(project: Any) -> dict[str, Any]:
    """Ensure memories pane exists."""
    payload = build_memories_payload(project)
    if payload is None:
        return {"status": "skipped", "reason": "no project memory tmux sessions"}
    return run_wezterm_panes_driver(payload)


def wezterm_window_exists(title: str) -> bool:
    """Check if WezTerm window with title exists."""
    try:
        result = subprocess.run(
            ["wezterm", "cli", "list", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        windows = json.loads(result.stdout)
        for window in windows:
            window_title = window.get("title", "")
            if title in window_title:
                return True
        return False
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def focus_wezterm_window(title: str) -> None:
    """Focus WezTerm window with title."""
    # WezTerm doesn't have a direct focus API, but we can try to activate it
    # In practice, this is a no-op on Windows as WezTerm windows are managed by the OS
    pass


def close_wezterm_window(title: str) -> bool:
    """Close WezTerm window with title."""
    try:
        # Find window ID by title
        result = subprocess.run(
            ["wezterm", "cli", "list", "--format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        windows = json.loads(result.stdout)
        for window in windows:
            window_title = window.get("title", "")
            if title in window_title:
                window_id = window.get("window_id")
                if window_id:
                    subprocess.run(
                        ["wezterm", "cli", "kill-window", "--window-id", str(window_id)],
                        capture_output=True,
                        check=False,
                        timeout=5,
                    )
                    return True
        return False
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        return False


def open_memory_window() -> dict[str, Any]:
    """Open memory window."""
    return {"status": "skipped", "reason": "global memory window retired"}


def _should_refresh_memories(*, rebuild: bool, open_memory: bool, refresh_memories: bool) -> bool:
    """Check if memories should be refreshed."""
    return (open_memory or refresh_memories) or not rebuild


def open_grid_window(
    project: Any,
    *,
    recover: bool = False,
    rebuild: bool = False,
    open_memory: bool = False,
    refresh_memories: bool = False,
) -> dict[str, Any]:
    """Open grid window for project."""
    template_name = str(getattr(project, "template_name", "") or "")
    if _project_primary_seat_id(project) == "memory":
        window_title = f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}-workers"
        if rebuild and wezterm_window_exists(window_title):
            close_wezterm_window(window_title)
        if recover and not rebuild and wezterm_window_exists(window_title):
            focus_wezterm_window(window_title)
            result: dict[str, Any] = {"status": "ok", "window_id": "", "recovered": True}
        else:
            result = run_wezterm_panes_driver(build_workers_payload(project))
            result["recovered"] = False
            result["rebuilt"] = bool(rebuild)
        if _should_refresh_memories(
            rebuild=rebuild,
            open_memory=open_memory,
            refresh_memories=refresh_memories,
        ):
            result["memories"] = ensure_memories_pane(project)
        else:
            print(
                "agent_admin_window: DEPRECATED: --rebuild no longer refreshes memories by default. "
                "Use --refresh-memories (or --open-memory) to restore legacy behavior.",
                file=sys.stderr,
            )
            result["memories"] = {
                "status": "skipped",
                "reason": "rebuild defaults to workers-only",
            }

        result["memory"] = open_memory_window()

        worker_count = len(_project_grid_seat_ids(project))
        worker_seats = worker_count
        if worker_seats <= 0:
            worker_seats = 1
        result["summary"] = (
            f"window open-grid: rebuilt project={project.name} seats={worker_seats} "
            f"{'memories=touched' if result['memories'].get('status') == 'ok' else 'memories=skipped'}"
        )
        return result

    if template_name not in frozenset({""}):
        print(
            f"agent_admin_window: unknown template_name {template_name!r}; "
            "falling back to v1 grid window",
            file=sys.stderr,
        )

    window_title = f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}"
    if rebuild and wezterm_window_exists(window_title):
        close_wezterm_window(window_title)
    if recover and not rebuild and wezterm_window_exists(window_title):
        focus_wezterm_window(window_title)
        result = {"status": "ok", "window_id": "", "recovered": True}
    else:
        result = run_wezterm_panes_driver(build_grid_payload(project))
        result["recovered"] = False
        result["rebuilt"] = bool(rebuild)
    if open_memory:
        result["memory"] = open_memory_window()
    return result


def reseed_pane(project: Any, seat_id: str) -> dict[str, str]:
    """Reseed a pane."""
    seat = str(seat_id).strip()
    if seat in _PRIMARY_SEAT_IDS:
        raise AgentAdminWindowError(f"cannot reseed primary seat pane ({seat})")

    # On Windows, we can't easily reseed a specific pane
    # So we just return success and let the user handle it manually
    return {"status": "ok", "project": project.name, "seat_id": seat, "note": "manual reseed required on Windows"}


def open_monitor_window(project: Any, sessions: dict[str, Any], engineers: dict[str, Any]) -> None:
    """Open monitor window."""
    if project.window_mode == "tabs-1up":
        open_project_tabs_window(project, sessions, engineers)
        return
    # For grid mode, use WezTerm
    payload = build_grid_payload(project)
    run_wezterm_panes_driver(payload)


def open_project_tabs_window(project: Any, sessions: dict[str, Any], engineers: dict[str, Any]) -> None:
    """Open project tabs window."""
    visible_engineer_ids = project.monitor_engineers or project.engineers
    if not visible_engineer_ids:
        raise AgentAdminWindowError(f"{project.name} has no monitor engineers configured")

    resolved_sessions: list[Any] = []
    for engineer_id in visible_engineer_ids:
        session = sessions.get(engineer_id)
        if session is None:
            continue
        if tmux_has_session(session.session):
            resolved_sessions.append(session)

    if not resolved_sessions:
        raise AgentAdminWindowError(
            f"{project.name} has no running engineer sessions to open. "
            "Start the needed seats first, then reopen the project window."
        )

    tabs = []
    for session in resolved_sessions:
        engineer = engineers.get(session.engineer_id)
        title = f"{project.name}:{engineer.display_name if engineer else session.engineer_id}"
        tabs.append({
            "name": title,
            "command": shell_attach_command(session)
        })

    payload = {
        "mode": "tabs",
        "title": f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}",
        "tabs": tabs,
    }
    run_wezterm_panes_driver(payload)


def open_dashboard_window(projects: list[Any]) -> None:
    """Open dashboard window."""
    if not projects:
        raise AgentAdminWindowError("No projects configured")

    tabs = []
    for project in projects:
        tabs.append({
            "name": project.name,
            "command": project_monitor_shell_command(project)
        })

    payload = {
        "mode": "tabs",
        "title": f"{_GRID_WINDOW_TITLE_PREFIX}dashboard",
        "tabs": tabs,
    }
    run_wezterm_panes_driver(payload)


def open_engineer_window(session: Any, engineer: Any | None) -> None:
    """Open engineer window."""
    title = display_name_for(engineer, session.engineer_id)
    payload = {
        "title": f"{_GRID_WINDOW_TITLE_PREFIX}{title}",
        "panes": [
            {"label": title, "command": shell_attach_command(session)}
        ]
    }
    run_wezterm_panes_driver(payload)


def display_name_for(engineer: Any | None, fallback: str) -> str:
    """Get display name for engineer."""
    if engineer and getattr(engineer, "display_name", ""):
        return engineer.display_name
    return fallback


# Re-export functions from original module that don't need changes
build_monitor_layout = _original.build_monitor_layout
