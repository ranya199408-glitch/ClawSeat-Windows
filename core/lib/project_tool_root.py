"""Project-scoped user-tool root helpers (MULTI-IDENTITY-056)."""
from __future__ import annotations

from pathlib import Path

from real_home import real_user_home
from project_binding import validate_project_name


def project_tool_root(project: str, home: Path | None = None) -> Path:
    """Return ``~/.agent-runtime/projects/<project>`` under ``home``."""
    base = Path(home or real_user_home()).expanduser()
    return base / ".agent-runtime" / "projects" / validate_project_name(project)


def project_tool_subpath(project: str, subpath: str, home: Path | None = None) -> Path:
    """Return a child path under the project-scoped tool root."""
    return project_tool_root(project, home=home) / subpath.lstrip("/")
