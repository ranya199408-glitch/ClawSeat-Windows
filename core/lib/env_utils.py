"""Shared .env parsing helpers."""
from __future__ import annotations

import shlex
from pathlib import Path


def parse_env_text(text: str) -> dict[str, str]:
    """Parse shell-style KEY=VALUE lines from text."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, raw_value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        raw_value = raw_value.strip()
        if not raw_value:
            values[key] = ""
            continue
        try:
            parsed = shlex.split(raw_value, posix=True)
        except ValueError:
            parsed = []
        values[key] = parsed[0] if parsed else raw_value.strip("\"'")
    return values


def parse_env_file(path: Path | str) -> dict[str, str]:
    """Parse a .env file path, returning an empty dict if it is absent/unreadable."""
    if not path:
        return {}
    env_path = Path(path)
    try:
        text = env_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, TypeError, ValueError):
        return {}
    return parse_env_text(text)
