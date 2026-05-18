#!/usr/bin/env python3
"""WezTerm driver for ClawSeat Windows port.

Reads a JSON payload on stdin describing the panes/tabs to open,
then drives WezTerm via its CLI to create windows with multiple panes.

Each pane runs a command (typically `tmux attach -t <session>`).

SAFETY GUARANTEES:
  • This driver never executes ANY tmux command directly.
  • Closing a WezTerm pane sends SIGHUP → bash → tmux client detach.
    The inner tmux session survives.
  • Partial build failure closes the half-built window.
  • Bad input returns structured error JSON without opening a window.
  • Hard cap of 8 panes per window.

Payload on stdin::
  {
    "title": "install",
    "panes": [
      {"label": "memory", "command": "tmux attach -t '=install-memory-claude'"},
      {"label": "planner", "command": "tmux attach -t '=install-planner-claude'"},
      ...
    ],
    "send_delay_ms": 250
  }

Or tabs mode::
  {
    "mode": "tabs",
    "title": "clawseat-memories",
    "tabs": [
      {"name": "project1", "command": "tmux attach -t '=project1-memory'"},
      ...
    ]
  }

Output on stdout (stdlib json)::
  {"status": "ok", "panes_created": 6, "window_id": "w0"}

Failure output::
  {"status": "error", "reason": "...", "fix": "..."}
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

MAX_PANES = 8
DEFAULT_SEND_DELAY_MS = 250
BUILD_TIMEOUT_SECONDS = 30.0


def wezterm_cli(args: list[str], timeout: float = BUILD_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    """Execute a wezterm cli command."""
    # Use full path to wezterm.exe from local deps
    wezterm_exe = os.environ.get("WEZTERM_EXE", "wezterm")
    cmd = [wezterm_exe, "cli", *args]
    env = os.environ.copy()
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def get_window_panes(window_id: str) -> list[str]:
    """Get list of pane IDs in a window."""
    result = wezterm_cli(["list", "--format", "json"])
    if result.returncode != 0:
        return []
    try:
        panes = json.loads(result.stdout)
        return [p["pane_id"] for p in panes if str(p.get("window_id")) == window_id]
    except (json.JSONDecodeError, KeyError):
        return []


def _validate_panes_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (validated_payload, error). Exactly one is non-None."""
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
        label = "".join(c for c in label if c.isprintable())[:64]
        cleaned.append({"label": label, "command": command})

    title = payload.get("title", "ClawSeat")
    if not isinstance(title, str):
        title = "ClawSeat"
    title = "".join(c for c in title if c.isprintable())[:128]

    delay = payload.get("send_delay_ms", DEFAULT_SEND_DELAY_MS)
    if not isinstance(delay, (int, float)) or delay < 0 or delay > 5000:
        delay = DEFAULT_SEND_DELAY_MS

    return {"title": title, "panes": cleaned, "send_delay_ms": int(delay)}, None


def _validate_tabs_payload(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Validate tabs mode payload."""
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
        if not isinstance(name, str) or not name:
            return None, {"status": "error", "reason": f"tab[{i}].name must be non-empty string"}
        if not isinstance(command, str):
            return None, {"status": "error", "reason": f"tab[{i}].command must be string"}
        cleaned.append({"name": name, "command": command})

    delay = payload.get("send_delay_ms", DEFAULT_SEND_DELAY_MS)
    if not isinstance(delay, (int, float)) or delay < 0 or delay > 5000:
        delay = DEFAULT_SEND_DELAY_MS

    return {
        "mode": "tabs",
        "title": title,
        "tabs": cleaned,
        "send_delay_ms": int(delay),
    }, None


def _validate_payload(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return (validated_payload, error). Exactly one is non-None."""
    if not isinstance(payload, dict):
        return None, {"status": "error", "reason": "payload must be a JSON object"}

    mode = payload.get("mode", "panes")
    if mode == "tabs":
        return _validate_tabs_payload(payload)
    if mode != "panes":
        return None, {"status": "error", "reason": f"unknown mode: {mode!r}"}

    return _validate_panes_payload(payload)


def _build_panes_layout(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a window with multiple panes using WezTerm CLI."""
    title = payload["title"]
    panes = payload["panes"]
    delay_s = payload["send_delay_ms"] / 1000.0

    # Spawn initial window and get pane ID
    # Use absolute path for cwd to avoid path issues
    import os
    cwd = os.environ.get("CLAWSEAT_ROOT", ".")
    result = wezterm_cli(["spawn", "--cwd", cwd, "--new-window"])
    if result.returncode != 0:
        return {"status": "error", "reason": f"wezterm spawn failed: {result.stderr or result.stdout}"}

    first_pane_id = result.stdout.strip()
    if not first_pane_id:
        return {"status": "error", "reason": "wezterm spawn returned empty pane_id"}

    # Get window ID from the pane
    result = wezterm_cli(["list", "--format", "json"])
    window_id = None
    if result.returncode == 0:
        try:
            all_panes = json.loads(result.stdout)
            for p in all_panes:
                if str(p.get("pane_id")) == first_pane_id:
                    window_id = str(p.get("window_id"))
                    break
        except json.JSONDecodeError:
            pass

    if not window_id:
        return {"status": "error", "reason": "could not determine window_id from spawned pane"}

    created_panes = [first_pane_id]

    # Split panes - vertical layout (left to right)
    for i in range(1, len(panes)):
        # Always split Right for vertical column layout
        result = wezterm_cli(["split-pane", "--pane-id", created_panes[i - 1], "--right", "--"])
        if result.returncode != 0:
            # Close the window on failure
            wezterm_cli(["kill-window", "--window-id", window_id])
            return {
                "status": "error",
                "reason": f"split-pane step {i}/{len(panes) - 1} failed: {result.stderr or result.stdout}",
                "fix": "window may be too small for the layout",
            }
        new_pane_id = result.stdout.strip()
        if not new_pane_id:
            wezterm_cli(["kill-window", "--window-id", window_id])
            return {
                "status": "error",
                "reason": f"split-pane step {i} returned empty pane_id",
            }
        created_panes.append(new_pane_id)

    # Wait for shell prompts
    if delay_s > 0:
        time.sleep(delay_s)

    # Send commands to each pane
    for pane_id, spec in zip(created_panes, panes):
        label = spec["label"]
        command = spec["command"]

        # Set pane title via user var - include project name and planner role
        if label:
            # Format: "planner@project" or just "planner" if no project context
            pane_title = label
            if title and title != "ClawSeat" and not title.startswith("clawseat-"):
                pane_title = f"{label}@{title}"
            elif title.startswith("clawseat-"):
                project_name = title[len("clawseat-"):]
                pane_title = f"{label}@{project_name}"
            wezterm_cli(["set-pane-title", "--pane-id", pane_id, pane_title])

        # Send command
        if command:
            result = wezterm_cli(["send-text", "--pane-id", pane_id, command + "\n"])
            if result.returncode != 0:
                wezterm_cli(["kill-window", "--window-id", window_id])
                return {
                    "status": "error",
                    "reason": f"send-text failed for pane {label!r}: {result.stderr or result.stdout}",
                }

    return {
        "status": "ok",
        "panes_created": len(created_panes),
        "window_id": window_id,
    }


def _build_tabs_layout(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a window with multiple tabs using WezTerm CLI."""
    title = payload["title"]
    tabs = payload["tabs"]
    delay_s = payload["send_delay_ms"] / 1000.0

    # Spawn initial window
    result = wezterm_cli(["spawn", "--cwd", "."])
    if result.returncode != 0:
        return {"status": "error", "reason": f"wezterm spawn failed: {result.stderr or result.stdout}"}

    first_pane_id = result.stdout.strip()
    if not first_pane_id:
        return {"status": "error", "reason": "wezterm spawn returned empty pane_id"}

    # Get window ID
    result = wezterm_cli(["list", "--format", "json"])
    window_id = None
    if result.returncode == 0:
        try:
            all_panes = json.loads(result.stdout)
            for p in all_panes:
                if str(p.get("pane_id")) == first_pane_id:
                    window_id = str(p.get("window_id"))
                    break
        except json.JSONDecodeError:
            pass

    if not window_id:
        return {"status": "error", "reason": "could not determine window_id from spawned pane"}

    # Send first tab command
    if delay_s > 0:
        time.sleep(delay_s)

    first_tab = tabs[0]
    if first_tab["command"]:
        result = wezterm_cli(["send-text", "--pane-id", first_pane_id, first_tab["command"] + "\n"])
        if result.returncode != 0:
            wezterm_cli(["kill-window", "--window-id", window_id])
            return {
                "status": "error",
                "reason": f"send-text failed for tab 0: {result.stderr or result.stdout}",
            }

    # Create additional tabs
    for i, tab in enumerate(tabs[1:], start=1):
        result = wezterm_cli(["spawn", "--window-id", window_id, "--cwd", "."])
        if result.returncode != 0:
            wezterm_cli(["kill-window", "--window-id", window_id])
            return {
                "status": "error",
                "reason": f"failed to create tab {i}: {result.stderr or result.stdout}",
            }

        pane_id = result.stdout.strip()
        if not pane_id:
            wezterm_cli(["kill-window", "--window-id", window_id])
            return {"status": "error", "reason": f"tab {i} returned empty pane_id"}
        if tab["command"]:
            if delay_s > 0:
                time.sleep(delay_s)
            result = wezterm_cli(["send-text", "--pane-id", pane_id, tab["command"] + "\n"])
            if result.returncode != 0:
                wezterm_cli(["kill-window", "--window-id", window_id])
                return {
                    "status": "error",
                    "reason": f"send-text failed for tab {i}: {result.stderr or result.stdout}",
                }

    return {
        "status": "ok",
        "tabs_created": len(tabs),
        "window_id": window_id,
    }


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "reason": f"invalid JSON: {exc}"}))
        raise SystemExit(2)

    validated, error = _validate_payload(payload)
    if error:
        print(json.dumps(error))
        raise SystemExit(2)

    assert validated is not None

    if validated.get("mode") == "tabs":
        result = _build_tabs_layout(validated)
    else:
        result = _build_panes_layout(validated)

    print(json.dumps(result))

    if result.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
