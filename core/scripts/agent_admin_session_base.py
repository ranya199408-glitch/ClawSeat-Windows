from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = str(_REPO_ROOT / "core" / "lib")
if _CORE_LIB not in sys.path:
    sys.path.insert(0, _CORE_LIB)

from project_binding import load_binding  # noqa: E402
from env_utils import parse_env_file  # noqa: E402
from project_tool_root import project_tool_root  # noqa: E402
from real_home import real_user_home  # noqa: E402
from state import Seat, open_db, upsert_seat  # noqa: E402


TMUX_COMMAND_RETRIES = 2
TMUX_COMMAND_TIMEOUT_SECONDS = 8.0
TMUX_COMMAND_RETRY_DELAY_SECONDS = 1.0

# Stability window for _assert_session_running (audit finding #5).
# Some agent CLIs (notably codex) can spawn-then-exit within 1-3s of
# tmux new-session — long enough to pass the immediate post-launch
# check, short enough to leave a dead pane that tmux GC'd before
# the operator notices. Re-verify after this window to catch transient
# launch failures that the immediate check would miss.
SESSION_STABILITY_WINDOW_SECONDS = 4.0

# ── iTerm integration ─────────────────────────────────────────────────────────

# AppleScript closes the single iTerm session/pane that owns the given tty —
# NOT the entire tab.  Closing the tab nukes all sibling panes (workers grid
# disappearance RCA, 2026-04-25).  `close s` targets just that
# session; remaining panes in the same tab are untouched.
_ITERM_CLOSE_SCRIPT_TEMPLATE = """\
tell application "iTerm"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if tty of s is "{tty}" then
                    close s
                    return "ok"
                end if
            end repeat
        end repeat
    end repeat
    return "not_found"
end tell\
"""


def _get_tmux_tty(session_name: str) -> str | None:
    """Return the tty of the first attached client for a tmux session, or None."""
    try:
        result = subprocess.run(
            ["tmux", "list-clients", "-t", session_name, "-F", "#{client_tty}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0].strip() or None
    except Exception:  # silent-ok: best-effort tty lookup; missing client is normal (no attached client)
        pass
    return None


def _close_iterm_pane_by_tty(tty: str) -> dict:
    """Close the iTerm pane (session) owning the given tty via osascript.

    Returns {"status": "ok"|"not_found"|"error", "detail": str|None}.
    Never raises — all errors are returned in the dict.

    Closes only the matching split/pane, leaving sibling panes in the same
    tab intact.  See AppleScript template comment for the 2026-04-25 RCA.
    """
    script = _ITERM_CLOSE_SCRIPT_TEMPLATE.format(tty=tty)
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
        if result.returncode != 0:
            return {
                "status": "error",
                "detail": result.stderr.strip() or f"rc={result.returncode}",
            }
        output = result.stdout.strip()
        if output == "ok":
            return {"status": "ok", "detail": None}
        return {"status": "not_found", "detail": output}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


class SessionStartError(RuntimeError):
    """Raised when a seat session cannot be created into a verified running tmux state."""


@dataclass
class SessionHooks:
    agentctl_path: str
    launcher_path: str
    load_project: Callable[[str], Any]
    apply_template: Callable[[Any, Any], None]
    reconcile_session_runtime: Callable[[Any], Any]
    ensure_provider_credential_ready: Callable[[Any], None]
    write_session: Callable[[Any], None]
    load_project_sessions: Callable[[str], dict[str, Any]]
    project_template_context: Callable[[Any], Any]
    load_engineers: Callable[[], dict[str, Any]]
    tmux_has_session: Callable[[str], bool]
    build_monitor_layout: Callable[[Any, dict[str, Any]], None]


_SANDBOX_TOOL_SEED_SUBPATHS = (
    ".lark-cli",
    "Library/Application Support/iTerm2",
    "Library/Preferences/com.googlecode.iterm2.plist",
    ".config/gemini",
    ".gemini",
    ".config/codex",
    ".codex",
)


def _real_home_for_tool_seeding() -> Path:
    module = sys.modules.get("agent_admin_session")
    real_home_fn = getattr(module, "real_user_home", real_user_home) if module is not None else real_user_home
    return real_home_fn()


def _engineer_profile_path(engineer_id: str) -> Path:
    return _real_home_for_tool_seeding() / ".agents" / "engineers" / engineer_id / "engineer.toml"


def _project_tool_source_home(project_name: str | None, real_home: Path) -> Path:
    if not project_name:
        return real_home
    binding = load_binding(project_name)
    if binding is None or binding.tools_isolation != "per-project":
        return real_home
    return project_tool_root(project_name, home=real_home)


def seed_user_tool_dirs(
    runtime_home: Path,
    real_home: Path | None = None,
    project_name: str | None = None,
) -> list[str]:
    """Link user-level tool dirs/files from the real HOME into a runtime HOME.

    Existing sandbox-owned copies are backed up under
    ``.sandbox-pre-seed-backup`` before being replaced with symlinks.
    """
    runtime_home = Path(runtime_home)
    real_home = Path(real_home) if real_home is not None else _real_home_for_tool_seeding()
    source_home = _project_tool_source_home(project_name, real_home)
    try:
        if runtime_home.resolve() == real_home.resolve():
            return []
    except OSError:
        if str(runtime_home) == str(real_home):
            return []
    changed: list[str] = []
    backup_base = runtime_home / ".sandbox-pre-seed-backup"

    for subpath in _SANDBOX_TOOL_SEED_SUBPATHS:
        src = source_home / subpath
        tgt = runtime_home / subpath
        if not src.exists():
            continue

        if tgt.is_symlink():
            try:
                if tgt.resolve() == src.resolve():
                    continue
            except OSError:
                pass
            tgt.unlink()
        elif tgt.exists():
            backup_path = backup_base / f"{subpath}.{time.time_ns()}"
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tgt), str(backup_path))

        tgt.parent.mkdir(parents=True, exist_ok=True)
        if not tgt.exists():
            tgt.symlink_to(src)
            changed.append(subpath)

    return changed
