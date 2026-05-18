"""Shared tmux primitives — single source of truth for session existence checks.

Use exact-match (`-t "=<name>"`) semantics by default. Substring match was a
source of name-collision bugs (e.g. session "mem" colliding with "memory");
see docs/rfc/AUDIT-2026-05-12-CODE-QUALITY.md §3.8 / §10.5.
"""
from __future__ import annotations

import shutil
import subprocess


def tmux_session_alive(name: str, *, timeout: float = 3.0) -> bool:
    """Return True iff a tmux session with the exact name `name` exists.

    Uses `tmux has-session -t "=<name>"` (the `=` prefix forces exact match).
    Returns False if tmux is not installed, the call times out, or any
    subprocess error occurs.
    """
    if not name:
        return False
    if shutil.which("tmux") is None:
        return False
    try:
        result = subprocess.run(
            ["tmux", "has-session", "-t", f"={name}"],
            capture_output=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0
