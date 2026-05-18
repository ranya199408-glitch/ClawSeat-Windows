from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import projects_registry

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = str(_REPO_ROOT / "core" / "lib")
if _CORE_LIB not in sys.path:
    sys.path.insert(0, _CORE_LIB)

from tmux import tmux_session_alive as _tmux_session_alive_shared  # noqa: E402


class AgentAdminWindowError(Exception):
    pass


class SeatNotFoundInWindow(AgentAdminWindowError):
    pass


TMUX_COMMAND_RETRIES = 2
TMUX_COMMAND_TIMEOUT_SECONDS = 8.0
TMUX_COMMAND_RETRY_DELAY_SECONDS = 1.0
ITERM_SCRIPT_APPS = ("iTerm", "iTerm2")
ITERM_SCRIPT_RETRIES = 3
_ITERM_PANES_DRIVER = Path(__file__).resolve().with_name("iterm_panes_driver.py")
_WAIT_FOR_SEAT_SCRIPT = _REPO_ROOT / "scripts" / "wait-for-seat.sh"
_GRID_WINDOW_TITLE_PREFIX = "clawseat-"
_MEMORIES_WINDOW_TITLE = "clawseat-memories"
_MAX_ITERM_PANES = 8
_V1_GRID_TEMPLATES = frozenset({""})

# Per-project primary seat ids — the seat that is the user's first dialog
# entry (orchestrator + memory + research). v1 templates name it "ancestor";
# v2 templates name it "memory" per RFC-001 §2.4. Code that special-
# cases the primary seat (window grid, recovery hooks, brief env injection,
# reseed restrictions) checks set membership instead of literal equality.
_PRIMARY_SEAT_IDS = frozenset({"ancestor", "memory"})


def _project_primary_seat_id(project: Any) -> str:
    """Return the project's primary seat id (first engineer in template order
    matching _PRIMARY_SEAT_IDS). Falls back to 'memory' for v2 canonicality."""
    for raw_engineer_id in getattr(project, "engineers", []) or []:
        engineer_id = str(raw_engineer_id)
        if engineer_id in _PRIMARY_SEAT_IDS:
            return engineer_id
    return "memory"


def tmux(
    args: list[str],
    check: bool = True,
    capture_output: bool = False,
    text: bool = True,
    timeout: float = TMUX_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    cmd = ["tmux", *args]
    return subprocess.run(cmd, check=check, capture_output=capture_output, text=text, timeout=timeout)


def tmux_with_retry(
    args: list[str],
    *,
    label: str,
    check: bool = True,
    retries: int = TMUX_COMMAND_RETRIES,
    timeout: float = TMUX_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    last_error: subprocess.CalledProcessError | subprocess.TimeoutExpired | None = None
    for attempt in range(1, retries + 1):
        try:
            return tmux(
                args,
                check=check,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            last_error = exc
            if attempt >= retries:
                break
            print(
                f"tmux_retry: {label} attempt={attempt}/{retries} failed: {exc!s}",
                file=sys.stderr,
            )
            time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)

    if isinstance(last_error, subprocess.TimeoutExpired):
        raise AgentAdminWindowError(
            f"{label} failed after {retries} attempt(s): timeout after "
            f"{TMUX_COMMAND_TIMEOUT_SECONDS:.1f}s each, args={args}"
        ) from last_error
    if isinstance(last_error, subprocess.CalledProcessError):
        detail = str(last_error.stderr or last_error.stdout or "").strip()
        raise AgentAdminWindowError(
            f"{label} failed after {retries} attempt(s), exit={last_error.returncode}, "
            f"detail={detail}, args={args}"
        ) from last_error
    raise AgentAdminWindowError(f"{label} failed after {retries} attempt(s): args={args}")


def tmux_has_session(session: str) -> bool:
    return _tmux_session_alive_shared(session, timeout=TMUX_COMMAND_TIMEOUT_SECONDS)


def tmux_window_panes(window_target: str) -> list[dict[str, int | str]]:
    proc = tmux_with_retry(
        [
            "list-panes",
            "-t",
            window_target,
            "-F",
            "#{pane_id}\t#{pane_width}\t#{pane_height}\t#{pane_left}\t#{pane_top}",
        ],
        label=f"tmux_window_panes({window_target})",
        check=True,
    )
    panes: list[dict[str, int | str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        pane_id, width, height, left, top = parts
        panes.append(
            {
                "pane_id": pane_id,
                "width": int(width),
                "height": int(height),
                "left": int(left),
                "top": int(top),
            }
        )
    return panes


def monitor_attach_command(session: str) -> str:
    quoted = shlex.quote(session)
    return f"exec env -u TMUX tmux attach -t {quoted} || exec $SHELL -l"


def build_attach_command(
    *,
    session: str,
    workspace: str,
    fallback_to_shell: bool = True,
) -> str:
    """
    Compose a deterministic shell command for attaching into an existing tmux session.

    The command is intentionally strict:
    - run in target workspace
    - unset TMUX to avoid nested-session corruption
    - fail hard to shell fallback if attach fails (iterm-only policy)
    """
    attach_target = shlex.quote(session)
    workspace_dir = shlex.quote(workspace)
    fallback = " || exec $SHELL -l" if fallback_to_shell else ""
    return f"cd {workspace_dir} && exec env -u TMUX tmux attach -t {attach_target}{fallback}"


def _iterm_script_command(command: str, *, context: str) -> str:
    cleaned = command.strip()
    if not cleaned:
        raise AgentAdminWindowError(f"empty iterm command for {context}")
    return applescript_quote(cleaned)


def shell_attach_command(session: Any) -> str:
    return build_attach_command(session=session.session, workspace=session.workspace)


def project_monitor_shell_command(project: Any) -> str:
    # Use env -u TMUX to avoid nested-tmux interference.
    return build_attach_command(session=project.monitor_session, workspace=project.repo_root)


_FRONTSTAGE_ENGINEER_IDS = frozenset({"koder", "frontstage"})


def _is_frontstage_engineer(engineer_id: str) -> bool:
    # koder (alias "frontstage", role frontstage-supervisor) is an OpenClaw
    # agent, NOT a back-end tmux seat. If a project's monitor_engineers list
    # includes it by mistake, silently skip rather than auto-spawning a
    # ghost tmux session that clobbers the real OpenClaw identity.
    return engineer_id in _FRONTSTAGE_ENGINEER_IDS


def _project_grid_seat_ids(project: Any) -> list[str]:
    """Return the non-primary project seats (workers) in roster order."""
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
    wait_script = wait_for_seat_script or _WAIT_FOR_SEAT_SCRIPT
    seats = _project_grid_seat_ids(project)
    primary_seat_id = _project_primary_seat_id(project)
    if not seats:
        print(
            f"agent_admin_window: project {project.name} has no worker seats; "
            f"falling back to {primary_seat_id}-only grid",
            file=sys.stderr,
        )

    panes: list[dict[str, str]] = [
        {
            "label": primary_seat_id,
            "command": f"tmux attach -t '={project.name}-{primary_seat_id}'",
        }
    ]
    for seat_id in seats:
        panes.append(
            {
                "label": seat_id,
                "command": (
                    "bash "
                    + shlex.quote(str(wait_script))
                    + " "
                    + shlex.quote(project.name)
                    + " "
                    + shlex.quote(seat_id)
                ),
            }
        )
    return {"title": f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}", "panes": panes}


def _worker_attach_pane(
    *,
    project_name: str,
    seat_id: str,
    wait_script: Path,
) -> dict[str, str]:
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
    wait_script = wait_for_seat_script or _WAIT_FOR_SEAT_SCRIPT
    workers = _project_grid_seat_ids(project)
    if "planner" in workers:
        workers = ["planner", *[seat_id for seat_id in workers if seat_id != "planner"]]
    if not workers:
        raise AgentAdminWindowError(f"project {project.name} has no worker seats for v2 workers window")
    if len(workers) > _MAX_ITERM_PANES:
        raise AgentAdminWindowError(
            f"project {project.name} has {len(workers)} worker seats; "
            f"workers window supports at most {_MAX_ITERM_PANES} panes"
        )

    if len(workers) == 4:
        panes = [
            _worker_attach_pane(
                project_name=project.name,
                seat_id=seat_id,
                wait_script=wait_script,
            )
            for seat_id in workers
        ]
    else:
        main_worker = workers[0]
        right_workers = workers[1:]
        panes = [
            _worker_attach_pane(
                project_name=project.name,
                seat_id=main_worker,
                wait_script=wait_script,
            )
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
    del project  # The shared memories window is built from all registered project memory sessions.
    # Only render tabs for projects whose memory tmux session is actually live.
    # Stale registry entries (project registered but seat killed) would otherwise
    # produce "tmux attach failed → -zsh fallback" garbage tabs that accumulate
    # forever across rebuilds.
    live_sessions = set(_tmux_session_names())
    tabs = [
        {
            "name": entry.name,
            "command": f"tmux attach -t '={entry.tmux_name}'",
        }
        for entry in projects_registry.enumerate_projects()
        if entry.name and entry.tmux_name and entry.tmux_name in live_sessions
    ]
    if not tabs:
        memory_sessions = sorted(
            session
            for session in live_sessions
            if session.endswith("-memory")
        )
        tabs = [
            {
                "name": session[: -len("-memory")],
                "command": f"tmux attach -t '={session}'",
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


def ensure_memories_pane(project: Any) -> dict[str, Any]:
    payload = build_memories_payload(project)
    if payload is None:
        return {"status": "skipped", "reason": "no project memory tmux sessions"}
    return run_iterm_panes_driver(payload)


def run_iterm_panes_driver(payload: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(_ITERM_PANES_DRIVER)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"rc={result.returncode}"
        raise AgentAdminWindowError(f"iTerm pane driver failed: {detail}")
    try:
        decoded = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AgentAdminWindowError(
            f"iTerm pane driver returned invalid JSON: {exc}: {stdout}"
        ) from exc
    if not isinstance(decoded, dict):
        raise AgentAdminWindowError("iTerm pane driver returned a non-object payload")
    if decoded.get("status") != "ok":
        raise AgentAdminWindowError(decoded.get("reason") or "iTerm pane driver returned non-ok status")
    return decoded


def _iterm_window_script(app_name: str, title: str, *, focus: bool) -> str:
    quoted_title = applescript_quote(title)
    if focus:
        return textwrap.dedent(
            f'''
            tell application "{app_name}"
              activate
              repeat with w in windows
                try
                  if (name of w as string) contains "{quoted_title}" then
                    select w
                    return "1"
                  end if
                end try
              end repeat
              return "0"
            end tell
            '''
        ).strip()
    return textwrap.dedent(
        f'''
        tell application "{app_name}"
          repeat with w in windows
            try
              if (name of w as string) contains "{quoted_title}" then
                return "1"
              end if
            end try
          end repeat
          return "0"
        end tell
        '''
    ).strip()


def iterm_window_exists(title: str) -> bool:
    if shutil.which("osascript") is None:
        return False
    for app_name in ITERM_SCRIPT_APPS:
        result = subprocess.run(
            ["osascript", "-e", _iterm_window_script(app_name, title, focus=False)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return True
    return False


def focus_iterm_window(title: str) -> None:
    if shutil.which("osascript") is None:
        return
    for app_name in ITERM_SCRIPT_APPS:
        result = subprocess.run(
            ["osascript", "-e", _iterm_window_script(app_name, title, focus=True)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return


def close_iterm_window(title: str) -> bool:
    if shutil.which("osascript") is None:
        return False
    quoted_title = applescript_quote(title)
    for app_name in ITERM_SCRIPT_APPS:
        script = textwrap.dedent(
            f'''
            tell application "{app_name}"
              repeat with w in windows
                try
                  if (name of w as string) contains "{quoted_title}" then
                    close w
                    return "1"
                  end if
                end try
              end repeat
              return "0"
            end tell
            '''
        ).strip()
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            return True
    return False


def open_memory_window() -> dict[str, Any]:
    """Deprecated no-op for the removed v1 global machine memory window."""
    return {"status": "skipped", "reason": "global memory window retired"}


def _should_refresh_memories(
    *,
    rebuild: bool,
    open_memory: bool,
    refresh_memories: bool,
) -> bool:
    return (open_memory or refresh_memories) or not rebuild


def open_grid_window(
    project: Any,
    *,
    recover: bool = False,
    rebuild: bool = False,
    open_memory: bool = False,
    refresh_memories: bool = False,
) -> dict[str, Any]:
    template_name = str(getattr(project, "template_name", "") or "")
    if _project_primary_seat_id(project) == "memory":
        window_title = f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}-workers"
        if rebuild and iterm_window_exists(window_title):
            close_iterm_window(window_title)
        if recover and not rebuild and iterm_window_exists(window_title):
            focus_iterm_window(window_title)
            result: dict[str, Any] = {"status": "ok", "window_id": "", "recovered": True}
        else:
            result = run_iterm_panes_driver(build_workers_payload(project))
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
                "This legacy behavior is deprecated: use --refresh-memories (or --open-memory) "
                "to restore legacy behavior.",
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

    if template_name not in _V1_GRID_TEMPLATES:
        print(
            f"agent_admin_window: unknown template_name {template_name!r}; "
            "falling back to v1 grid window",
            file=sys.stderr,
        )

    window_title = f"{_GRID_WINDOW_TITLE_PREFIX}{project.name}"
    if rebuild and iterm_window_exists(window_title):
        close_iterm_window(window_title)
    if recover and not rebuild and iterm_window_exists(window_title):
        focus_iterm_window(window_title)
        result: dict[str, Any] = {"status": "ok", "window_id": "", "recovered": True}
    else:
        result = run_iterm_panes_driver(build_grid_payload(project))
        result["recovered"] = False
        result["rebuilt"] = bool(rebuild)
    if open_memory:
        result["memory"] = open_memory_window()
    return result


def _window_title(window: Any) -> str:
    for attr in ("title", "name"):
        value = getattr(window, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _iter_session_tree(session: Any) -> list[Any]:
    child_sessions = getattr(session, "sessions", None)
    if isinstance(child_sessions, list) and child_sessions:
        items: list[Any] = []
        for child in child_sessions:
            items.extend(_iter_session_tree(child))
        return items
    return [session]


def _iter_window_sessions(window: Any) -> list[Any]:
    sessions: list[Any] = []
    for tab in getattr(window, "tabs", []) or []:
        tab_sessions = getattr(tab, "sessions", None)
        if isinstance(tab_sessions, list) and tab_sessions:
            for session in tab_sessions:
                sessions.extend(_iter_session_tree(session))
            continue
        current_session = getattr(tab, "current_session", None)
        if current_session is not None:
            sessions.extend(_iter_session_tree(current_session))
    return sessions


async def _session_seat_id(session: Any) -> str:
    getter = getattr(session, "async_get_variable", None)
    if getter is not None:
        try:
            value = await getter("user.seat_id")
        except Exception:  # noqa: BLE001 best-effort lookup
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()
    name = getattr(session, "name", "")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


async def _find_reseed_target_session(app: Any, project_name: str, seat_id: str) -> Any:
    target_window_title = f"{_GRID_WINDOW_TITLE_PREFIX}{project_name}"
    for window in getattr(app, "windows", []) or []:
        window_title = _window_title(window)
        if window_title and target_window_title not in window_title:
            continue
        for session in _iter_window_sessions(window):
            if await _session_seat_id(session) == seat_id:
                return session
    raise SeatNotFoundInWindow(
        f"seat '{seat_id}' not found in iTerm grid window '{target_window_title}'"
    )


async def _reseed_pane_async(connection: Any, project_name: str, seat_id: str) -> dict[str, str]:
    import iterm2  # type: ignore[import-not-found]

    app = await iterm2.async_get_app(connection)
    target = await _find_reseed_target_session(app, project_name, seat_id)

    activate = getattr(target, "async_activate", None)
    if activate is not None:
        try:
            await activate()
            await asyncio.sleep(0.1)
        except Exception:  # noqa: BLE001 focus is best-effort
            pass

    await target.async_send_text("\x03")
    await asyncio.sleep(0.05)

    wait_command = (
        "bash "
        + shlex.quote(str(_WAIT_FOR_SEAT_SCRIPT))
        + " "
        + shlex.quote(project_name)
        + " "
        + shlex.quote(seat_id)
    )
    window_title = f"{_GRID_WINDOW_TITLE_PREFIX}{project_name}"
    script = (
        'tell application "iTerm2"\n'
        "  repeat with w in windows\n"
        f'    if (name of w as text) contains "{_sanitize_applescript_text(window_title)}" then\n'
        "      repeat with t in tabs of w\n"
        "        repeat with s in sessions of t\n"
        '          tell s to set seatName to variable named "user.seat_id"\n'
        f'          if (seatName as text) is "{_sanitize_applescript_text(seat_id)}" then\n'
        f'            tell s to write text "{_sanitize_applescript_text(wait_command)}"\n'
        "            return\n"
        "          end if\n"
        "        end repeat\n"
        "      end repeat\n"
        "    end if\n"
        "  end repeat\n"
        f'  error "reseed-pane: seat \'{_sanitize_applescript_text(seat_id)}\' not found in iTerm grid window \'{_sanitize_applescript_text(window_title)}\'"\n'
        "end tell"
    )
    osascript(script)

    return {"status": "ok", "project": project_name, "seat_id": seat_id}


def reseed_pane(project: Any, seat_id: str) -> dict[str, str]:
    seat = str(seat_id).strip()
    if seat in _PRIMARY_SEAT_IDS:
        raise AgentAdminWindowError(f"cannot reseed primary seat pane ({seat})")
    try:
        import iterm2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AgentAdminWindowError(
            "iterm2 Python module not installed; run `pip3 install --user iterm2`"
        ) from exc

    holder: dict[str, dict[str, str]] = {}

    async def _main(connection: Any) -> None:
        holder["result"] = await _reseed_pane_async(connection, project.name, seat)

    try:
        iterm2.run_until_complete(_main, retry=True)
    except SeatNotFoundInWindow:
        raise
    except AgentAdminWindowError:
        raise
    except Exception as exc:  # noqa: BLE001 convert to CLI-friendly error
        raise AgentAdminWindowError(
            f"reseed-pane failed for {project.name}/{seat}: {exc}"
        ) from exc
    return holder["result"]


def _monitor_layout_target_sessions(project: Any, sessions: dict[str, Any]) -> list[Any]:
    frontstage_skipped: list[str] = []
    filtered_ids = []
    for engineer_id in project.monitor_engineers:
        if _is_frontstage_engineer(engineer_id):
            frontstage_skipped.append(engineer_id)
            continue
        filtered_ids.append(engineer_id)
    if frontstage_skipped:
        print(
            f"agent_admin_window: monitor layout skipped frontstage engineers "
            f"for {project.name}: {', '.join(frontstage_skipped)} "
            "(openclaw-managed, not tmux seats)",
            file=sys.stderr,
        )
    target_ids = filtered_ids[: max(1, project.monitor_max_panes)]
    resolved: list[Any] = []
    missing: list[str] = []
    for engineer_id in target_ids:
        session = sessions.get(engineer_id)
        if session is None or not tmux_has_session(session.session):
            missing.append(engineer_id)
            continue
        resolved.append(session)
    if not resolved:
        raise AgentAdminWindowError(
            f"{project.name} monitor layout has no running sessions. missing={missing}"
        )
    if missing:
        print(
            f"agent_admin_window: monitor layout skipped missing sessions for {project.name}: {', '.join(missing)}",
            file=sys.stderr,
        )
    return resolved


def build_monitor_layout(project: Any, sessions: dict[str, Any]) -> None:
    monitor = project.monitor_session
    if tmux_has_session(monitor):
        print(
            f"agent_admin_window: rebuilding monitor session '{monitor}' for {project.name}: killing existing session",
            file=sys.stderr,
        )
        tmux_with_retry(
            ["kill-session", "-t", monitor],
            label=f"kill existing monitor session {monitor}",
            check=False,
            retries=TMUX_COMMAND_RETRIES,
        )

    repo_root = project.repo_root
    visible_engineer_sessions = _monitor_layout_target_sessions(project, sessions)
    if not visible_engineer_sessions:
        raise AgentAdminWindowError(f"{project.name} has no monitor engineers configured")

    visible_engineer_ids = [session.engineer_id for session in visible_engineer_sessions]

    def _label_pane(pane_id: str, engineer_id: str) -> None:
        # The inner attached tmux session pushes its own pane_title via OSC
        # escapes which silently overwrites `select-pane -T`. To keep labels
        # stable we store engineer_id in a per-pane user option (@seat) that
        # only our code writes, and reference it from pane-border-format.
        # We still call `select-pane -T` so users running ad-hoc tmux
        # commands see the friendly label too.
        tmux_with_retry(
            ["select-pane", "-t", pane_id, "-T", engineer_id],
            label=f"label monitor pane {pane_id}={engineer_id}",
            check=False,
        )
        tmux_with_retry(
            ["set-option", "-p", "-t", pane_id, "@seat", engineer_id],
            label=f"set pane @seat={engineer_id} on {pane_id}",
            check=False,
        )

    def _split_with_id(
        *,
        target: str,
        direction: str,
        attach: str,
        label: str,
    ) -> str:
        # `-P -F '#{pane_id}'` prints the new pane id so we can title it
        # immediately afterwards instead of guessing via list-panes diff.
        result = tmux_with_retry(
            [
                "split-window",
                direction,
                "-P",
                "-F",
                "#{pane_id}",
                "-t",
                target,
                "-c",
                repo_root,
                attach,
            ],
            label=label,
        )
        return result.stdout.strip()

    try:
        # Capture the first pane's id from new-session so we can label it.
        new_session_result = tmux_with_retry(
            [
                "new-session",
                "-P",
                "-F",
                "#{pane_id}",
                "-d",
                "-x",
                "240",
                "-y",
                "80",
                "-s",
                monitor,
                "-c",
                repo_root,
            ],
            label=f"new monitor session {monitor}",
        )
        first_pane_id = new_session_result.stdout.strip() or f"{monitor}:0.0"
        first_engineer = visible_engineer_sessions[0]
        tmux_with_retry(
            [
                "send-keys",
                "-t",
                first_pane_id,
                monitor_attach_command(first_engineer.session),
                "C-m",
            ],
            label=f"seed first monitor pane attach {first_engineer.engineer_id}",
        )
        _label_pane(first_pane_id, first_engineer.engineer_id)

        if len(visible_engineer_sessions) >= 2:
            second = visible_engineer_sessions[1]
            new_pane_id = _split_with_id(
                target=first_pane_id,
                direction="-h",
                attach=monitor_attach_command(second.session),
                label=f"split pane for second monitor seat {second.engineer_id}",
            )
            _label_pane(new_pane_id, second.engineer_id)

        panes = tmux_window_panes(f"{monitor}:0")
        if len(visible_engineer_sessions) >= 3 and panes:
            leftmost = min(panes, key=lambda item: (int(item["left"]), int(item["top"])))
            leftmost_id = str(leftmost["pane_id"])
            third = visible_engineer_sessions[2]
            new_pane_id = _split_with_id(
                target=leftmost_id,
                direction="-v",
                attach=monitor_attach_command(third.session),
                label=f"split pane for third monitor seat {third.engineer_id}",
            )
            _label_pane(new_pane_id, third.engineer_id)

        panes = tmux_window_panes(f"{monitor}:0")
        if len(visible_engineer_sessions) >= 4 and panes:
            rightmost = max(panes, key=lambda item: (int(item["left"]), -int(item["top"])))
            rightmost_id = str(rightmost["pane_id"])
            fourth = visible_engineer_sessions[3]
            new_pane_id = _split_with_id(
                target=rightmost_id,
                direction="-v",
                attach=monitor_attach_command(fourth.session),
                label=f"split pane for fourth monitor seat {fourth.engineer_id}",
            )
            _label_pane(new_pane_id, fourth.engineer_id)

        # 5+ panes: split the largest remaining pane for each extra seat,
        # alternating axis based on shape so the grid stays roughly uniform.
        # `select-layout tiled` below rebalances regardless, but starting
        # from balanced splits avoids transient pane-too-small failures
        # for TUIs (claude/codex/gemini need ≥ ~80×24).
        for index in range(4, len(visible_engineer_sessions)):
            panes = tmux_window_panes(f"{monitor}:0")
            if not panes:
                break
            largest = max(panes, key=lambda item: int(item["width"]) * int(item["height"]))
            largest_id = str(largest["pane_id"])
            direction = "-h" if int(largest["width"]) >= int(largest["height"]) * 2 else "-v"
            engineer = visible_engineer_sessions[index]
            new_pane_id = _split_with_id(
                target=largest_id,
                direction=direction,
                attach=monitor_attach_command(engineer.session),
                label=f"split pane for monitor seat #{index + 1} {engineer.engineer_id}",
            )
            _label_pane(new_pane_id, engineer.engineer_id)

        # ── Nested-tmux ergonomics ──────────────────────────────────
        # Monitor session is a thin layout shell wrapping N inner sessions.
        # Without these knobs the outer prefix (Ctrl+B) clashes with each
        # inner session's prefix, so users have to press Ctrl+B Ctrl+B to
        # send a prefix to the inner — fragile and surprising.
        #
        # Fix: rebind outer prefix to Ctrl+A (and disable mouse). Outer
        # becomes essentially invisible; Ctrl+B reaches the inner Claude /
        # Codex / Gemini TUI directly. Pane navigation: Ctrl+A then arrow.
        tmux_with_retry(
            ["set-option", "-t", monitor, "prefix", "C-a"],
            label=f"set monitor prefix C-a for {monitor}",
            check=False,
        )
        tmux_with_retry(
            ["set-option", "-t", monitor, "prefix2", "None"],
            label=f"disable secondary prefix for {monitor}",
            check=False,
        )
        tmux_with_retry(
            ["set-option", "-t", monitor, "mouse", "off"],
            label=f"disable mouse on {monitor}",
            check=False,
        )
        # Forward focus events to inner sessions — Claude / Codex / Gemini
        # TUIs use them to show/hide their cursor and refresh prompts. Off
        # by default in tmux; with nested clients the inner TUI looks idle.
        tmux_with_retry(
            ["set-option", "-t", monitor, "focus-events", "on"],
            label=f"enable focus-events on {monitor}",
            check=False,
        )
        # Tell tmux this terminal supports xterm-style key encodings so
        # modifier+key chords (Shift+Tab, Ctrl+Enter) survive the nesting.
        tmux_with_retry(
            ["set-window-option", "-t", f"{monitor}:0", "xterm-keys", "on"],
            label=f"enable xterm-keys for {monitor}",
            check=False,
        )

        # Make labels visible: pane border at the top showing the engineer id.
        # Also disable automatic-rename so the window name stays as the project
        # (without this, all panes report cmd=tmux and the window name flickers).
        tmux_with_retry(
            ["set-option", "-t", monitor, "pane-border-status", "top"],
            label=f"enable pane-border-status for {monitor}",
            check=False,
        )
        # Prefer @seat (set by _label_pane) since the inner attached session
        # may rewrite pane_title via terminal OSC escapes.
        tmux_with_retry(
            [
                "set-option",
                "-t",
                monitor,
                "pane-border-format",
                " #{?@seat,#{@seat},#{pane_title}} ",
            ],
            label=f"set pane-border-format for {monitor}",
            check=False,
        )
        tmux_with_retry(
            ["set-window-option", "-t", f"{monitor}:0", "automatic-rename", "off"],
            label=f"disable automatic-rename for {monitor}",
            check=False,
        )
        tmux_with_retry(
            ["rename-window", "-t", f"{monitor}:0", project.name],
            label=f"rename monitor window to {project.name}",
            check=False,
        )

        layout = "tiled"
        if project.window_mode == "tabs-1up":
            layout = "even-vertical"
        if len(visible_engineer_sessions) == 4:
            layout = "tiled"
        tmux_with_retry(
            ["select-layout", "-t", f"{monitor}:0", layout],
            label=f"set monitor layout {monitor}",
            check=False,
        )
    except AgentAdminWindowError as exc:
        # Roll back partial layout to avoid half-open tmux sessions.
        if tmux_has_session(monitor):
            tmux_with_retry(
                ["kill-session", "-t", monitor],
                label=f"rollback monitor session {monitor}",
                check=False,
                retries=TMUX_COMMAND_RETRIES,
            )
        raise AgentAdminWindowError(
            f"{project.name} monitor layout failed for session '{monitor}' (engineers={visible_engineer_ids}): {exc}"
        ) from exc


def osascript(script: str) -> None:
    result = subprocess.run(["osascript", "-e", script], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            ["osascript", "-e", script],
            output=result.stdout,
            stderr=result.stderr,
        )


def _sanitize_applescript_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def run_iterm_script(script_factory: Any) -> None:
    # iTerm-preferred with graceful degradation: try iTerm AppleScript first,
    # raise AgentAdminWindowError if unavailable. Callers should catch this
    # and fall back to tmux-only mode (tmux attach -t <session>).
    attempts = 0
    last_error: subprocess.CalledProcessError | None = None
    for app_name in ITERM_SCRIPT_APPS:
        for attempt in range(1, ITERM_SCRIPT_RETRIES + 1):
            attempts += 1
            try:
                osascript(script_factory(app_name))
                return
            except subprocess.CalledProcessError as exc:
                last_error = exc
                if attempt >= ITERM_SCRIPT_RETRIES:
                    break
                print(
                    f"iterm_script_retry: app={app_name} attempt={attempt}/{ITERM_SCRIPT_RETRIES} rc={exc.returncode}",
                    file=sys.stderr,
                )
                time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)
        if last_error is not None and last_error.returncode != 0:
            last_code = getattr(last_error, "returncode", "n/a")
            last_detail = ""
            if getattr(last_error, "stderr", None):
                last_detail = (getattr(last_error, "stderr") or "").strip()
            if not last_detail and getattr(last_error, "output", None):
                last_detail = (getattr(last_error, "output") or "").strip()
            print(
                f"iterm_script_failed_once: app={app_name} total_attempts={attempts} last_rc={last_code} "
                f"detail={last_detail}",
                file=sys.stderr,
            )
    if last_error is not None:
        raise AgentAdminWindowError(
            f"AppleScript failed after retries; apps={', '.join(ITERM_SCRIPT_APPS)} "
            f"last_rc={getattr(last_error, 'returncode', 'n/a')}"
        ) from last_error


def applescript_quote(value: str) -> str:
    return _sanitize_applescript_text(value)


def iterm_run_command(command: str, title: str | None = None) -> None:
    # Ensure command content is deterministic before writing into AppleScript text.
    escaped_command = _iterm_script_command(command, context="iterm_run_command")
    title_lines = ""
    if title:
        escaped_title = applescript_quote(title)
        title_lines = f'\n      set name to "{escaped_title}"'

    def build_script(app_name: str) -> str:
        # IMPORTANT: anchor the new window in a local AppleScript variable
        # (targetWindow). `current window` is iTerm-wide mutable state — when
        # two agent-admin invocations race (e.g. koder fires start_seat for
        # several seats in parallel), each osascript sees the OTHER's
        # just-created window as "current" and both end up writing into the
        # same window while the other is left blank. Pinning to the local
        # variable returned by `create window` is the iTerm-official way to
        # avoid this race without serialising the callers.
        return textwrap.dedent(
            f'''
            tell application "{app_name}"
              activate
              set targetWindow to (create window with default profile)
              tell current session of targetWindow
                {title_lines.strip()}
                write text "{escaped_command}"
              end tell
            end tell
            '''
            ).strip()

    run_iterm_script(build_script)


def open_monitor_window(project: Any, sessions: dict[str, Any], engineers: dict[str, Any]) -> None:
    if project.window_mode == "tabs-1up":
        open_project_tabs_window(project, sessions, engineers)
        return
    iterm_run_command(project_monitor_shell_command(project))


def open_project_tabs_window(project: Any, sessions: dict[str, Any], engineers: dict[str, Any]) -> None:
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

    def build_script(app_name: str) -> str:
        # Note: we intentionally do NOT close existing project tabs before
        # creating the new window. Closing tabs kills their shell process,
        # which detaches running agent sessions (including the caller if it
        # runs open-monitor from inside one of those tabs). Old windows are
        # left for the user to close manually or are replaced naturally when
        # the tmux session reattaches in the new tab.
        # Anchor every write to the local `projectWindow` (and, for added
        # tabs, to a local `newTab`) so a concurrent osascript creating its
        # own window cannot steal `current window` and redirect our writes.
        # See iterm_run_command() for the rationale.
        lines = [
            f'tell application "{app_name}"',
            "  activate",
            "  set projectWindow to (create window with default profile)",
        ]

        for tab_index, session in enumerate(resolved_sessions):
            command = _iterm_script_command(shell_attach_command(session), context=f"monitor tab {session.engineer_id}")
            engineer = engineers.get(session.engineer_id)
            title = applescript_quote(f"{project.name}:{engineer.display_name if engineer else session.engineer_id}")
            if tab_index == 0:
                # The first tab is the one created implicitly with the window.
                lines.append("  tell current session of projectWindow")
                lines.append(f'    set name to "{title}"')
                lines.append(f'    write text "{command}"')
                lines.append("  end tell")
            else:
                lines.append("  tell projectWindow")
                lines.append("    set newTab to (create tab with default profile)")
                lines.append("    tell current session of newTab")
                lines.append(f'      set name to "{title}"')
                lines.append(f'      write text "{command}"')
                lines.append("    end tell")
                lines.append("  end tell")

        lines.append("end tell")
        return "\n".join(lines)

    run_iterm_script(build_script)


def open_dashboard_window(projects: list[Any]) -> None:
    if not projects:
        raise AgentAdminWindowError("No projects configured")

    def build_script(app_name: str) -> str:
        # Same anti-race pattern as open_project_tabs_window / iterm_run_command:
        # anchor to local `dashboardWindow` and (for added tabs) local `newTab`
        # rather than iTerm's mutable `current window` / `current tab`.
        lines = [
            f'tell application "{app_name}"',
            "  activate",
            "  set dashboardWindow to (create window with default profile)",
        ]

        for tab_index, project in enumerate(projects):
            command = _iterm_script_command(
                project_monitor_shell_command(project),
                context="open_dashboard_window",
            )
            if tab_index == 0:
                lines.append("  tell current session of dashboardWindow")
                lines.append(f'    write text "{command}"')
                lines.append("  end tell")
            else:
                lines.append("  tell dashboardWindow")
                lines.append("    set newTab to (create tab with default profile)")
                lines.append("    tell current session of newTab")
                lines.append(f'      write text "{command}"')
                lines.append("    end tell")
                lines.append("  end tell")

        lines.append("end tell")
        return "\n".join(lines)

    run_iterm_script(build_script)


def open_engineer_window(session: Any, engineer: Any | None) -> None:
    iterm_run_command(shell_attach_command(session), title=display_name_for(engineer, session.engineer_id))


def display_name_for(engineer: Any | None, fallback: str) -> str:
    if engineer and getattr(engineer, "display_name", ""):
        return engineer.display_name
    return fallback
