#!/usr/bin/env python3
"""iTerm2 Python API driver for ClawSeat native-panel monitor windows.

Reads a JSON payload on stdin describing the panes to open, then drives
iTerm2 via its Python API (https://iterm2.com/python-api/) to create one
window with N native iTerm panes in a balanced grid. Each pane runs a
single-layer `tmux attach -t <session>` so the Claude / Codex / Gemini
TUI gets fully native keyboard + mouse input — no nested tmux.

SAFETY GUARANTEES (covered by tests/test_iterm_panes_driver.py):
  • This driver never executes ANY tmux command directly. The only tmux
    activity is whatever the operator-supplied `command` field runs INSIDE
    each pane (typically `tmux attach -t <session>`), which by design is
    a client operation that can never delete a session.
  • Closing an iTerm pane sends SIGHUP → bash → tmux client detach. The
    inner tmux session survives; verified by test_session_survives_pane_close.
  • Partial build failure (e.g., iTerm refuses a split because the window
    is too small) closes the half-built window so the operator never sees
    a confusing 2-pane window when 6 were requested.
  • Bad input (non-list panes, n=0, n>8, unknown keys) returns a structured
    error JSON without ever opening an iTerm window.
  • Hard cap of 8 panes (per iTerm Python API smoke testing — at 9+ the
    minimum pane size is < 80 columns on a 27" 4K display and TUIs break).

Why this path: iTerm2's official tmux-integration docs
(https://iterm2.com/documentation-tmux-integration.html) call out nested
tmux as the reason `tmux -CC` exists; AppleScript split-pane is marked
Deprecated in iTerm's docs sidebar. The Python API's async_split_pane
returns the new Session synchronously so there's no p3-style race that
bit our earlier AppleScript prototype.

Payload on stdin::

    {
      "title": "install",                  // iTerm window title (string)
      "panes": [                            // list, length 1..8
        {"label": "memory",    "command": "tmux attach -t '=install-memory-claude'"},
        {"label": "planner",   "command": "tmux attach -t '=install-planner-claude'"},
        ...
      ],
      "send_delay_ms": 250                  // optional, default 250ms before send_text
    }

Output on stdout (stdlib json):

    {"status": "ok", "panes_created": 6, "window_id": "w0"}

Failure output on stdout (driver still exits 0; ClawSeat caller checks status field):

    {"status": "error", "reason": "...", "fix": "..."}

Requires iTerm2's Python API to be enabled
(Preferences → General → Magic → Enable Python API) and the `iterm2`
module installed (`pip install --user iterm2`).
"""
from __future__ import annotations

import asyncio
import re
import json
import shlex
import sys
from typing import Any

try:
    import iterm2  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — surfaced as a friendly runtime error
    print(
        json.dumps({
            "status": "error",
            "reason": "iterm2 module not installed",
            "fix": "pip3 install --user --break-system-packages iterm2",
        }),
        file=sys.stderr,
    )
    raise SystemExit(2)


# Hard cap. At 9+ panes on a 27" 4K display each pane is below the ~80 col
# minimum that claude/codex/gemini need; testing showed they corrupt their
# own UI rather than gracefully degrade. Operators wanting more should
# split into multiple windows or tabs.
MAX_PANES = 8

# Default delay before async_send_text — the new pane's shell sources
# .zshrc / .bashrc, which can take 100-300ms (pyenv rehash, prompt setup).
# Sending text before the prompt is ready means it lands as MOTD output
# and is NEVER interpreted by the shell. 250ms covers the 95th percentile.
DEFAULT_SEND_DELAY_MS = 250

# Wall-clock guard: build never blocks longer than this. iTerm bugs
# occasionally hang async calls; better to fail loud than hang the caller.
BUILD_TIMEOUT_SECONDS = 30.0


# Layout shape → list of (parent_index, vertical) split instructions.
# parent_index is the index into the growing `sessions` list at the time
# of the split; vertical=True makes a new pane to the RIGHT of parent.
# Panes are filled in creation order, matching payload["panes"].
_LAYOUT_RECIPES: dict[int, list[tuple[int, bool]]] = {
    1: [],
    2: [(0, True)],
    3: [(0, True), (0, False)],                          # 2 cols, bottom-left
    4: [(0, True), (0, False), (1, False)],              # 2x2
    5: [(0, True), (1, True), (0, False), (1, False)],   # 3 cols top, 2 bottoms
    6: [(0, True), (1, True), (0, False), (1, False), (2, False)],  # 2x3
    7: [(0, True), (1, True), (0, False), (1, False), (2, False), (3, True)],
    8: [(0, True), (1, True), (0, False), (1, False), (2, False), (3, True), (4, True)],
}


def _validate_payload(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (validated_payload, error). Exactly one is non-None."""
    if not isinstance(payload, dict):
        return None, {"status": "error", "reason": "payload must be a JSON object"}
    mode = payload.get("mode", "panes")
    if mode == "tabs":
        return _validate_tabs_payload(payload)
    if mode != "panes":
        return None, {"status": "error", "reason": f"unknown mode: {mode!r}"}
    panes = payload.get("panes")
    if not isinstance(panes, list):
        return None, {"status": "error", "reason": "panes must be a list"}
    n = len(panes)
    if n < 1:
        return None, {"status": "error", "reason": "panes list is empty"}
    if n > MAX_PANES:
        return None, {
            "status": "error",
            "reason": f"{n} panes exceeds MAX_PANES={MAX_PANES}",
            "fix": "split into multiple windows/tabs",
        }
    cleaned: list[dict[str, str]] = []
    for i, p in enumerate(panes):
        if not isinstance(p, dict):
            return None, {"status": "error", "reason": f"pane[{i}] must be an object"}
        label = p.get("label", "")
        command = p.get("command", "")
        if not isinstance(label, str):
            return None, {"status": "error", "reason": f"pane[{i}].label must be string"}
        if not isinstance(command, str):
            return None, {"status": "error", "reason": f"pane[{i}].command must be string"}
        # Strip control characters from labels — iTerm rejects \n in titles.
        label = "".join(c for c in label if c.isprintable())[:64]
        cleaned.append({"label": label, "command": command})
    title = payload.get("title", "ClawSeat")
    if not isinstance(title, str):
        title = "ClawSeat"
    title = "".join(c for c in title if c.isprintable())[:128]
    delay = payload.get("send_delay_ms", DEFAULT_SEND_DELAY_MS)
    if not isinstance(delay, (int, float)) or delay < 0 or delay > 5000:
        delay = DEFAULT_SEND_DELAY_MS

    # Optional `recipe` field overrides _LAYOUT_RECIPES[n] for callers that
    # need non-balanced layouts (e.g. v2 workers window with planner main left
    # 50% + N-1 workers in right grid; or v2 memories window with max-2-rows
    # column-major fill). Recipe is a list of [parent_idx, vertical_bool] pairs;
    # length must equal n-1.
    recipe = payload.get("recipe")
    if recipe is not None:
        if not isinstance(recipe, list):
            return None, {"status": "error", "reason": "recipe must be a list when provided"}
        if len(recipe) != n - 1:
            return None, {
                "status": "error",
                "reason": f"recipe length {len(recipe)} != n-1 ({n - 1})",
                "fix": "recipe must contain exactly n-1 split steps",
            }
        cleaned_recipe: list[tuple[int, bool]] = []
        for i, step in enumerate(recipe):
            if not isinstance(step, list) or len(step) != 2:
                return None, {"status": "error", "reason": f"recipe[{i}] must be [parent_idx, vertical_bool]"}
            parent_idx, vertical = step
            if not isinstance(parent_idx, int) or parent_idx < 0 or parent_idx > i:
                return None, {"status": "error", "reason": f"recipe[{i}] parent_idx invalid: {parent_idx}"}
            if not isinstance(vertical, bool):
                return None, {"status": "error", "reason": f"recipe[{i}] vertical must be bool"}
            cleaned_recipe.append((parent_idx, vertical))
        return {"title": title, "panes": cleaned, "send_delay_ms": int(delay), "recipe": cleaned_recipe}, None
    return {"title": title, "panes": cleaned, "send_delay_ms": int(delay)}, None


def _validate_tabs_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    title = payload.get("title")
    if not isinstance(title, str):
        return None, {"status": "error", "reason": "title must be string for tabs mode"}
    title = "".join(c for c in title if c.isprintable())[:128]
    if not title:
        return None, {"status": "error", "reason": "title must not be empty for tabs mode"}

    tabs = payload.get("tabs")
    if not isinstance(tabs, list):
        return None, {"status": "error", "reason": "tabs must be a list"}
    if not tabs:
        return None, {"status": "error", "reason": "tabs list is empty"}

    cleaned: list[dict[str, str]] = []
    for i, tab in enumerate(tabs):
        if not isinstance(tab, dict):
            return None, {"status": "error", "reason": f"tab[{i}] must be an object"}
        name = tab.get("name")
        command = tab.get("command")
        if not isinstance(name, str):
            return None, {"status": "error", "reason": f"tab[{i}].name must be string"}
        if not name or any(not c.isprintable() for c in name) or len(name) > 64:
            return None, {
                "status": "error",
                "reason": f"tab[{i}].name must be printable and <=64 chars",
            }
        if not isinstance(command, str):
            return None, {"status": "error", "reason": f"tab[{i}].command must be string"}
        cleaned.append({"name": name, "command": command})

    ensure = payload.get("ensure", True)
    if not isinstance(ensure, bool):
        return None, {"status": "error", "reason": "ensure must be bool when provided"}

    delay = payload.get("send_delay_ms", DEFAULT_SEND_DELAY_MS)
    if not isinstance(delay, (int, float)) or delay < 0 or delay > 5000:
        delay = DEFAULT_SEND_DELAY_MS

    return {
        "mode": "tabs",
        "title": title,
        "tabs": cleaned,
        "ensure": ensure,
        "send_delay_ms": int(delay),
    }, None


async def _safe_close_window(window: Any) -> None:
    """Best-effort close of a half-built window. Never raises."""
    if window is None:
        return
    try:
        await window.async_close(force=True)
    except Exception:  # noqa: BLE001 silent-ok: cleanup best-effort
        pass


async def _safe_close_tab(tab: Any) -> bool:
    """Best-effort close of a stale tab (sessions iterated, then tab.async_close).

    Returns True on success, False otherwise. Never raises.
    """
    if tab is None:
        return False
    # iterm2 SDK closes tabs via tab.async_close(force=True) when available;
    # fall back to closing the underlying session(s).
    closer = getattr(tab, "async_close", None)
    if closer is not None:
        try:
            await closer(force=True)
            return True
        except Exception:  # noqa: BLE001 fall through to session-level close
            pass
    sessions_attr = getattr(tab, "sessions", None) or []
    closed_any = False
    for session in sessions_attr:
        sess_closer = getattr(session, "async_close", None)
        if sess_closer is None:
            continue
        try:
            await sess_closer(force=True)
            closed_any = True
        except Exception:  # noqa: BLE001 silent-ok: cleanup best-effort
            pass
    return closed_any


async def _build_layout(connection: Any, payload: dict[str, Any]) -> dict[str, Any]:
    title = payload["title"]
    panes = payload["panes"]
    delay_s = payload["send_delay_ms"] / 1000.0
    n = len(panes)

    # Materialize the App first — without it, window.current_tab can be None
    # (the SDK populates the tree as part of get_app, not Window.create).
    try:
        await iterm2.async_get_app(connection)
    except Exception as exc:  # noqa: BLE001 broad catch is correct: we want to surface
        return {"status": "error", "reason": f"async_get_app failed: {exc!r}"}

    window = None
    try:
        window = await iterm2.Window.async_create(connection)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": f"async_create window failed: {exc!r}"}
    if window is None:
        return {"status": "error", "reason": "iTerm refused to create a window"}

    try:
        try:
            await window.async_set_title(title)
        except Exception:  # noqa: BLE001 silent-ok: title is cosmetic, older iTerm may lack it
            pass

        if window.current_tab is None or window.current_tab.current_session is None:
            await _safe_close_window(window)
            return {
                "status": "error",
                "reason": "iTerm window has no initial session",
                "fix": "upgrade iTerm to 3.4+ with Python API enabled",
            }

        # Use payload-supplied recipe if provided, else fall back to balanced
        # _LAYOUT_RECIPES[n] for backwards compat with v1 callers.
        recipe = payload.get("recipe") or _LAYOUT_RECIPES[n]
        sessions: list[Any] = [window.current_tab.current_session]
        for step_idx, (parent_idx, vertical) in enumerate(recipe, start=1):
            try:
                parent = sessions[parent_idx]
                new_pane = await parent.async_split_pane(vertical=vertical)
            except Exception as exc:  # noqa: BLE001
                await _safe_close_window(window)
                return {
                    "status": "error",
                    "reason": (
                        f"split-pane step {step_idx}/{len(recipe)} failed: "
                        f"{exc!r}"
                    ),
                    "fix": "iTerm window may be too small for the layout",
                }
            if new_pane is None:
                await _safe_close_window(window)
                return {
                    "status": "error",
                    "reason": (
                        f"split-pane step {step_idx} returned None — "
                        "iTerm refused (window too small?)"
                    ),
                    "fix": "resize the iTerm window or reduce the pane count",
                }
            sessions.append(new_pane)

        # Wait for shell prompts to be ready before sending commands.
        # Without this, send_text races shell startup and commands can be
        # dropped (observed in early prototypes).
        if delay_s > 0:
            await asyncio.sleep(delay_s)

        for session, spec in zip(sessions, panes):
            label = spec["label"]
            command = spec["command"]
            if label:
                try:
                    await session.async_set_name(label)
                except Exception:  # noqa: BLE001 silent-ok: label is cosmetic
                    pass
                setter = getattr(session, "async_set_variable", None)
                if setter is not None:
                    try:
                        await setter("user.seat_id", label)
                    except Exception:  # noqa: BLE001 silent-ok: metadata is best-effort
                        pass
            if command:
                try:
                    await session.async_send_text(command + "\n")
                except Exception as exc:  # noqa: BLE001
                    # Don't tear down — partial command failure leaves a
                    # usable window with at least the other commands run.
                    print(
                        f"warn: send_text failed for pane {label!r}: {exc!r}",
                        file=sys.stderr,
                    )

        return {
            "status": "ok",
            "panes_created": len(sessions),
            "window_id": window.window_id,
        }
    except Exception as exc:  # noqa: BLE001 - bubble unknown failures with cleanup
        await _safe_close_window(window)
        return {"status": "error", "reason": f"unexpected: {exc!r}"}


async def _window_title(window: Any) -> str:
    getter = getattr(window, "async_get_variable", None)
    if getter is not None:
        try:
            value = await getter("user.window_title")
        except Exception:  # noqa: BLE001 best-effort marker lookup
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()

    for attr in ("title", "name"):
        value = getattr(window, attr, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _tab_name(tab: Any) -> str:
    session = getattr(tab, "current_session", None)
    if session is not None:
        getter = getattr(session, "async_get_variable", None)
        if getter is not None:
            try:
                value = await getter("user.tab_name")
            except Exception:  # noqa: BLE001 best-effort metadata lookup
                value = ""
            if isinstance(value, str) and value.strip():
                return value.strip()

    invoker = getattr(tab, "async_invoke_function", None)
    if invoker is not None:
        try:
            value = await invoker("iterm2.get_tab_title()")
        except Exception:  # noqa: BLE001 older iTerm SDKs may not support this
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()

    name = getattr(session, "name", "") if session is not None else ""
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


async def _tab_session_name(tab: Any) -> str:
    session = getattr(tab, "current_session", None)
    if session is None:
        return ""
    name = getattr(session, "name", "")
    if isinstance(name, str) and name.strip():
        return name.strip()
    getter = getattr(session, "async_get_variable", None)
    if getter is not None:
        try:
            value = await getter("session.name")
        except Exception:  # noqa: BLE001 best-effort SDK metadata lookup
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _tab_current_job(tab: Any) -> str:
    """Return the current foreground job name of the tab's current session.
    iTerm exposes this as the `jobName` variable (e.g. "tmux", "zsh", "node").
    Returns "" when unavailable — caller treats that as "unknown / not dead"."""
    session = getattr(tab, "current_session", None)
    if session is None:
        return ""
    # Test fakes set a `current_job` attribute directly; honor it first.
    job = getattr(session, "current_job", None)
    if isinstance(job, str) and job.strip():
        return job.strip()
    getter = getattr(session, "async_get_variable", None)
    if getter is None:
        return ""
    for var_name in ("jobName", "session.jobName"):
        try:
            value = await getter(var_name)
        except Exception:  # noqa: BLE001 best-effort SDK metadata lookup
            value = ""
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# Job names that indicate the tab is still inside a tmux client (attach is alive).
# Anything else (zsh, bash, sh, fish, etc.) means tmux attach has exited.
_TMUX_CLIENT_JOB_PREFIXES = ("tmux",)


def _job_indicates_tmux_client(job_name: str) -> bool:
    if not job_name:
        return False
    lower = job_name.lower()
    return any(lower.startswith(prefix) for prefix in _TMUX_CLIENT_JOB_PREFIXES)


def _command_is_tmux_attach(command: str) -> bool:
    """Heuristic: command opens a tmux client (attach, attach-session, a, etc.)."""
    if not command:
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    saw_tmux = False
    for token in tokens:
        if not saw_tmux:
            if token == "tmux" or token.endswith("/tmux"):
                saw_tmux = True
            continue
        if token in {"attach", "attach-session", "a", "at"}:
            return True
        if token.startswith("-"):
            continue
        # First non-flag token after tmux that isn't an attach verb → not attach.
        return False
    return False


def _expected_session_substr(spec: dict[str, str]) -> str:
    command = spec.get("command", "")
    if not command:
        return ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return ""
    for idx, token in enumerate(tokens):
        if token in {"-t", "--target"} and idx + 1 < len(tokens):
            return tokens[idx + 1].lstrip("=")
        for prefix in ("-t=", "--target="):
            if token.startswith(prefix):
                return token[len(prefix):].lstrip("=")
    return ""


def _memory_session_alive(project_name: str, session_name: str, expected_session: str) -> bool:
    if not project_name or not session_name:
        return False
    if expected_session and expected_session not in session_name:
        return False
    return re.fullmatch(
        rf"^{re.escape(project_name)}-memory(?:-(?:claude|codex|gemini))?$",
        session_name,
    ) is not None


def _session_name_matches(session_name: str, expected_tab_name: str, expected_session: str) -> bool:
    if expected_session and expected_session in session_name:
        return True
    return (
        session_name == expected_tab_name
        or session_name.startswith(f"{expected_tab_name} ")
        or session_name.startswith(f"{expected_tab_name}(")
    )


async def _tab_matches_expected(tab: Any, spec: dict[str, str]) -> tuple[bool, str | None]:
    expected_name = spec["name"]
    try:
        tab_name = await _tab_name(tab)
    except Exception as exc:  # noqa: BLE001 detection is best-effort, caller creates defensively
        return False, f"tab-name detection failed for {expected_name!r}: {exc!r}"
    if not tab_name:
        return False, f"tab-name detection returned empty while looking for {expected_name!r}"
    if tab_name != expected_name:
        return False, None

    session_name = await _tab_session_name(tab)
    expected_session = _expected_session_substr(spec)
    if not session_name:
        return False, f"session.name unavailable for tab marker {expected_name!r}"
    if _session_name_matches(session_name, expected_name, expected_session):
        return True, None
    target = expected_session or expected_name
    return (
        False,
        (
            f"tab marker {expected_name!r} has session.name {session_name!r}, "
            f"expected {target!r}"
        ),
    )


async def _tab_attach_died(tab: Any, spec: dict[str, str]) -> bool:
    """True iff the tab's marker matches the spec name AND the tab's
    launching tmux-attach command is no longer the foreground job. This is
    the "marker says X but tmux client exited" state — caller should reuse
    the tab and re-send the command rather than create a new tab."""
    expected_name = spec.get("name", "")
    if not expected_name:
        return False
    command = spec.get("command", "")
    if not _command_is_tmux_attach(command):
        return False  # only meaningful for tmux-attach style commands
    try:
        tab_name = await _tab_name(tab)
    except Exception:  # noqa: BLE001 best-effort metadata lookup
        return False
    if tab_name != expected_name:
        return False
    job = await _tab_current_job(tab)
    if not job:
        return False  # unknown → don't claim it's dead
    return not _job_indicates_tmux_client(job)


async def _find_existing_tab(
    window: Any, spec: dict[str, str]
) -> tuple[bool, Any | None, str | None]:
    """Scan existing tabs for one that matches spec.

    Returns (matched, reuse_tab, detection_failure):
      matched=True  → fully attached and working; skip.
      reuse_tab=<tab> → marker matches but the launching tmux-attach has
                       exited; caller should reuse the tab and re-send
                       the command (not create a new tab).
      detection_failure=<msg> → marker matches but session-name doesn't
                                (different tmux session); caller will
                                create a new tab.
    """
    detection_failure: str | None = None
    reuse_tab: Any | None = None
    for tab in getattr(window, "tabs", []) or []:
        # Check attach-died FIRST: a tab whose marker matches but whose
        # tmux-attach has exited would otherwise pass _tab_matches_expected
        # via the session_name==marker fallback, and we'd incorrectly skip
        # it instead of re-sending the attach.
        if reuse_tab is None and await _tab_attach_died(tab, spec):
            reuse_tab = tab
            continue
        matched, failure = await _tab_matches_expected(tab, spec)
        if matched:
            return True, None, None
        if failure and detection_failure is None:
            detection_failure = failure
    return False, reuse_tab, detection_failure


async def _mark_tab(tab: Any, spec: dict[str, str]) -> None:
    """Set tab/session title and user.tab_name marker. Cheap, does not enter
    tmux control mode — safe to run during Phase 1 before any command runs."""
    session = getattr(tab, "current_session", None)
    if session is None:
        raise RuntimeError(f"tab {spec['name']!r} has no current session")

    tab_setter = getattr(tab, "async_set_title", None)
    if tab_setter is not None:
        try:
            await tab_setter(spec["name"])
        except Exception:  # noqa: BLE001 tab title is cosmetic; marker below is durable
            pass

    try:
        await session.async_set_name(spec["name"])
    except Exception:  # noqa: BLE001 title is cosmetic; user.tab_name is the durable marker
        pass

    setter = getattr(session, "async_set_variable", None)
    if setter is not None:
        try:
            await setter("user.tab_name", spec["name"])
        except Exception:  # noqa: BLE001 metadata is best-effort
            pass


async def _configure_tab(tab: Any, spec: dict[str, str], delay_s: float) -> None:
    """Send the command to a tab whose marker has already been set by _mark_tab.
    This is the Phase 2 step that triggers tmux control mode on attach."""
    session = getattr(tab, "current_session", None)
    if session is None:
        raise RuntimeError(f"tab {spec['name']!r} has no current session")

    if delay_s > 0:
        await asyncio.sleep(delay_s)

    command = spec["command"]
    if command:
        try:
            await session.async_send_text(command + "\n")
        except Exception as exc:  # noqa: BLE001
            print(
                f"warn: send_text failed for tab {spec['name']!r}: {exc!r}",
                file=sys.stderr,
            )


async def _build_tabs_layout(connection: Any, payload: dict[str, Any]) -> dict[str, Any]:
    title = payload["title"]
    tabs = payload["tabs"]
    ensure = payload["ensure"]
    delay_s = payload["send_delay_ms"] / 1000.0

    try:
        app = await iterm2.async_get_app(connection)
    except Exception as exc:  # noqa: BLE001 broad catch is correct: we want to surface
        return {"status": "error", "reason": f"async_get_app failed: {exc!r}"}

    matching_windows = []
    for app_window in getattr(app, "windows", []) or []:
        if await _window_title(app_window) == title:
            matching_windows.append(app_window)
    if ensure and len(matching_windows) > 1:
        return {
            "status": "error",
            "reason": (
                f"multiple iTerm windows match title {title!r} — "
                "operator must close stale windows"
            ),
        }

    window = matching_windows[0] if ensure and matching_windows else None
    created_window = window is None
    if window is None:
        try:
            window = await iterm2.Window.async_create(connection)
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "reason": f"async_create window failed: {exc!r}"}
        if window is None:
            return {"status": "error", "reason": "iTerm refused to create a window"}
        try:
            await window.async_set_title(title)
        except Exception:  # noqa: BLE001 silent-ok: title is cosmetic, older iTerm may lack it
            pass
        setter = getattr(window, "async_set_variable", None)
        if setter is not None:
            try:
                await setter("user.window_title", title)
            except Exception:  # noqa: BLE001 marker is best-effort
                pass

    tabs_created = 0
    tabs_skipped = 0
    tab_results: list[dict[str, str]] = []
    # Track tab objects we've just created or skipped this run; prune must
    # not touch them. Tabs we just created have not had time for the tmux
    # attach inside them to update session.name yet, so the strict marker+
    # session check would falsely classify them as "stale" and kill them
    # immediately after creation.
    handled_tab_ids: set[int] = set()

    # Phase 1: create all tabs before sending any commands.
    # Sending tmux-attach via async_send_text to an already-created tab causes
    # iTerm to enter tmux control mode, which invalidates the window's Python
    # API handle — subsequent async_create_tab calls fail with INVALID_WINDOW_ID.
    # Fix: materialize every tab object first, then configure (send commands) in
    # a second pass after all tabs exist.
    pending: list[tuple[Any, dict[str, str], str, str]] = []  # (tab, spec, status, reason)
    try:
        for spec in tabs:
            status = "created"
            reason = ""
            if ensure and not created_window:
                matched, reuse_tab, detection_failure = await _find_existing_tab(window, spec)
                if matched:
                    tabs_skipped += 1
                    tab_results.append({"status": "skipped", "tab": spec["name"]})
                    for existing_tab in getattr(window, "tabs", []) or []:
                        ok, _ = await _tab_matches_expected(existing_tab, spec)
                        if ok:
                            handled_tab_ids.add(id(existing_tab))
                            break
                    continue
                if reuse_tab is not None:
                    # Marker matches but the previous tmux-attach has died
                    # (its tmux session was killed/restarted). Reuse the
                    # existing tab and re-send the command in Phase 2.
                    await _mark_tab(reuse_tab, spec)
                    pending.append((reuse_tab, spec, "reattached", ""))
                    handled_tab_ids.add(id(reuse_tab))
                    continue
                if detection_failure:
                    status = "detect-failure"
                    reason = detection_failure

            if created_window and len(pending) == 0 and getattr(window, "current_tab", None) is not None:
                tab = window.current_tab
            else:
                try:
                    tab = await window.async_create_tab()
                except Exception as exc:  # noqa: BLE001
                    if created_window:
                        await _safe_close_window(window)
                    tab_results.append({
                        "status": "error",
                        "tab": spec["name"],
                        "reason": f"create-tab failed: {exc!r}",
                    })
                    return {
                        "status": "error",
                        "reason": f"create-tab for {spec['name']!r} failed: {exc!r}",
                        "tabs_created": tabs_created,
                        "tabs_skipped": tabs_skipped,
                        "tabs": tab_results,
                        "window_id": getattr(window, "window_id", ""),
                    }
                if tab is None:
                    if created_window:
                        await _safe_close_window(window)
                    tab_results.append({
                        "status": "error",
                        "tab": spec["name"],
                        "reason": "create-tab returned None",
                    })
                    return {
                        "status": "error",
                        "reason": f"create-tab for {spec['name']!r} returned None",
                        "tabs_created": tabs_created,
                        "tabs_skipped": tabs_skipped,
                        "tabs": tab_results,
                        "window_id": getattr(window, "window_id", ""),
                    }

            # Set marker (title + user.tab_name) immediately so that
            # _find_existing_tab in subsequent specs doesn't mistake this
            # freshly created (but unconfigured) tab for a stale ghost.
            await _mark_tab(tab, spec)
            pending.append((tab, spec, status, reason))
            handled_tab_ids.add(id(tab))

        # Phase 2: configure all tabs (send commands) now that the window
        # structure is fully built and no more async_create_tab calls are needed.
        for tab, spec, status, reason in pending:
            await _configure_tab(tab, spec, delay_s)
            tabs_created += 1
            entry = {"status": status, "tab": spec["name"]}
            if reason:
                entry["reason"] = reason
            tab_results.append(entry)
    except Exception as exc:  # noqa: BLE001 - new windows should not be left half-built
        if created_window:
            await _safe_close_window(window)
        return {
            "status": "error",
            "reason": f"unexpected: {exc!r}",
            "tabs_created": tabs_created,
            "tabs_skipped": tabs_skipped,
            "tabs": tab_results,
            "window_id": getattr(window, "window_id", ""),
        }

    # Prune stale tabs not in the current spec when reusing an existing window.
    # Without this, every rebuild leaves dead tabs (e.g. -zsh fallback after a
    # tmux attach failure) accumulating forever.
    #
    # Strict matching for stale tabs: a tab is "expected" only when BOTH its
    # user.tab_name marker matches a spec.name AND its session.name matches
    # that spec's expected session substring. A tab whose marker says "install"
    # but is actually attached to "cartooner-front-memory-codex" (mismarker
    # from a historical driver bug) must still be pruned.
    #
    # CRITICAL: skip any tab we just created or matched in the loop above
    # (`handled_tab_ids`). A freshly created tab's `tmux attach` has not had
    # time to update session.name, so the strict match would falsely classify
    # it as stale and kill it immediately after creation.
    tabs_pruned = 0
    if ensure and not created_window:
        spec_by_name = {spec["name"]: spec for spec in tabs}
        for tab in list(getattr(window, "tabs", []) or []):
            if id(tab) in handled_tab_ids:
                continue
            try:
                tab_name = await _tab_name(tab)
            except Exception:  # noqa: BLE001 - if we can't read the name, leave it alone
                continue
            if not tab_name:
                continue
            matching_spec = spec_by_name.get(tab_name)
            if matching_spec is not None:
                expected_session = _expected_session_substr(matching_spec)
                try:
                    session_name = await _tab_session_name(tab)
                except Exception:  # noqa: BLE001 best-effort metadata lookup
                    session_name = ""
                if _memory_session_alive(tab_name, session_name, expected_session):
                    print(
                        f"INFO: prune skipped live memory tab={tab_name} "
                        f"session={session_name}",
                        file=sys.stderr,
                    )
                    continue
                # Marker matches a spec; verify session.name agrees before sparing the tab.
                matched, _ = await _tab_matches_expected(tab, matching_spec)
                if matched:
                    continue
            if await _safe_close_tab(tab):
                tabs_pruned += 1
                tab_results.append({"status": "pruned", "tab": tab_name})

    return {
        "status": "ok",
        "mode": "tabs",
        "tabs": tab_results,
        "tabs_created": tabs_created,
        "tabs_skipped": tabs_skipped,
        "tabs_pruned": tabs_pruned,
        "window_id": getattr(window, "window_id", ""),
    }


async def _main(connection):
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "reason": f"bad json on stdin: {exc}"}))
        return
    validated, err = _validate_payload(payload)
    if err is not None:
        print(json.dumps(err))
        return
    assert validated is not None  # for type checkers
    try:
        build = _build_tabs_layout if validated.get("mode") == "tabs" else _build_layout
        result = await asyncio.wait_for(
            build(connection, validated),
            timeout=BUILD_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        result = {
            "status": "error",
            "reason": f"build timed out after {BUILD_TIMEOUT_SECONDS}s",
            "fix": "iTerm may be hung; try `killall iTerm2` and rerun",
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    # iTerm's API server can take a moment to accept the first connection
    # after app launch or preference changes. Retry inside the SDK, but the
    # caller still wraps us in a wall-clock timeout so we never hang forever.
    iterm2.run_until_complete(_main, retry=True)
