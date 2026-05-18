"""Small shared helpers used across ClawSeat scripts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise ModuleNotFoundError(
            "clawseat requires Python 3.11+ OR tomli installed for Python <3.11. "
            "Install with: pip install tomli"
        ) from exc


def now_iso() -> str:
    """Return a UTC ISO-8601 timestamp using the repository's Z suffix convention."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def q(value: object) -> str:
    """Quote a value for TOML/JSON-compatible string embedding."""
    return json.dumps(value, ensure_ascii=False)


def q_array(values: Iterable[str]) -> str:
    """Format a string iterable as a TOML array."""
    return "[" + ", ".join(q(value) for value in values) + "]"


def load_toml(path: Path | str, *, missing_ok: bool = False) -> dict[str, Any] | None:
    """Load TOML from disk."""
    toml_path = Path(path)
    if missing_ok and not toml_path.exists():
        return None
    with toml_path.open("rb") as handle:
        return tomllib.load(handle)
