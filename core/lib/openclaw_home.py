"""Shared OpenClaw home discovery helper.

Resolution order:
1. OPENCLAW_HOME env override
2. `openclaw config file`
3. ~/.openclaw anchored to the supplied home (or real_user_home())
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Mapping

from real_home import real_user_home


def _expand_with_home(path_text: str, home: Path) -> Path:
    path_text = path_text.strip().strip('"').strip("'")
    if path_text == "~":
        return home
    if path_text.startswith("~/"):
        return home / path_text[2:]
    return Path(path_text).expanduser()


def discover_openclaw_home(
    *,
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    allow_cli: bool = True,
    timeout: float = 5.0,
    runner: Callable[..., object] = subprocess.run,
) -> Path:
    """Resolve the operator's OpenClaw home directory."""
    anchor = Path(home).expanduser() if home is not None else real_user_home()
    env_map = os.environ if env is None else env

    configured = str(env_map.get("OPENCLAW_HOME", "")).strip()
    if configured:
        return Path(configured).expanduser()

    if allow_cli:
        try:
            result = runner(
                ["openclaw", "config", "file"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and getattr(result, "returncode", 1) == 0:
            lines = [line.strip() for line in str(getattr(result, "stdout", "")).splitlines() if line.strip()]
            if lines:
                return _expand_with_home(lines[-1], anchor).parent

    return anchor / ".openclaw"
