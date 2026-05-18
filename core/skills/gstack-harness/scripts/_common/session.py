"""Session lookup helpers for gstack harness profiles."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from _utils import AGENTS_ROOT, load_toml

__all__ = [
    "discovered_session_data",
    "resolve_session_name",
    "session_path_for",
    "session_name_for",
]


def discovered_session_data(session_root: Path, project_name: str) -> dict[str, dict[str, Any]]:
    project_root = session_root / project_name
    if not project_root.exists():
        return {}
    discovered: dict[str, dict[str, Any]] = {}
    for session_path in sorted(project_root.glob("*/session.toml")):
        session = load_toml(session_path) or {}
        seat = str(session.get("engineer_id", session_path.parent.name)).strip() or session_path.parent.name
        discovered[seat] = session
    return discovered

def resolve_session_name(profile: HarnessProfile, seat: str) -> str:
    session_toml = AGENTS_ROOT / "sessions" / profile.project_name / seat / "session.toml"
    session_data = load_toml(session_toml)
    if session_data:
        session_name = str(session_data.get("session", "")).strip()
        if session_name:
            return session_name
    return seat


def session_path_for(profile: HarnessProfile, seat: str) -> Path:
    agents_root = profile.workspace_root.parent.parent
    return agents_root / "sessions" / profile.project_name / seat / "session.toml"


def session_name_for(profile: HarnessProfile, seat: str) -> str | None:
    session_path = session_path_for(profile, seat)
    session_data = load_toml(session_path)
    if not session_data:
        return None
    session_name = str(session_data.get("session", "")).strip()
    return session_name or None
