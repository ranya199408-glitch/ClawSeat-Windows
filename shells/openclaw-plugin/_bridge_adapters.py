"""
Adapter initialization for OpenClaw <-> ClawSeat bridge.

Handles TmuxCliAdapter loading (via importlib) and ClawSeatAdapter / profile init.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from typing import Any

from openclaw_bridge import _CLAWSEAT_ROOT

from core.adapter.clawseat_adapter import ClawseatAdapter


# ---------------------------------------------------------------------------
# TmuxCliAdapter initialization
# ---------------------------------------------------------------------------


# Guarded with a lock so a multi-threaded bridge host cannot double-load
# the adapter module (audit L8). Double-checked locking: the hot path
# still reads the cached reference without taking the lock.
_TMUX_ADAPTER_MODULE: Any = None
_TMUX_ADAPTER_LOCK = threading.Lock()


def _get_tmux_adapter_module() -> Any:
    global _TMUX_ADAPTER_MODULE
    if _TMUX_ADAPTER_MODULE is not None:
        return _TMUX_ADAPTER_MODULE
    with _TMUX_ADAPTER_LOCK:
        if _TMUX_ADAPTER_MODULE is None:
            _TMUX_ADAPTER_MODULE = _load_tmux_adapter()
    return _TMUX_ADAPTER_MODULE


def _load_tmux_adapter():
    """Load TmuxCliAdapter via importlib from the adapters path."""
    adapter_path = _CLAWSEAT_ROOT / "adapters" / "harness" / "tmux-cli" / "adapter.py"
    spec = importlib.util.spec_from_file_location("clawseat_tmux_cli_adapter", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load TmuxCliAdapter from {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["clawseat_tmux_cli_adapter"] = module
    spec.loader.exec_module(module)
    return module


def init_tmux_adapter(
    *,
    agents_root: str | Path | None = None,
    sessions_root: str | Path | None = None,
    workspaces_root: str | Path | None = None,
) -> Any:
    """Initialize a TmuxCliAdapter instance."""
    module = _get_tmux_adapter_module()
    return module.TmuxCliAdapter(
        agents_root=agents_root,
        sessions_root=sessions_root,
        workspaces_root=workspaces_root,
    )


# ---------------------------------------------------------------------------
# Profile initialization
# ---------------------------------------------------------------------------


def ensure_clawseat_profile(
    project_name: str,
    *,
    repo_root: str | Path | None = None,
    profile_path: str | Path | None = None,
) -> str:
    """
    Ensure a ClawSeat dynamic profile exists for the given project.

    Returns the resolved profile path.

    Special case: the canonical `install` project auto-seeds its dynamic profile
    from the shipped `examples/starter/profiles/install-openclaw.toml` when
    bootstrapping on a blank machine.
    """
    if profile_path is not None:
        candidate = Path(profile_path).expanduser()
        if candidate.exists():
            return str(candidate)

    # Check standard locations
    from resolve import dynamic_profile_path as _dpp
    dynamic_path = _dpp(project_name)
    if dynamic_path.exists():
        return str(dynamic_path)

    legacy_path = Path(f"/tmp/{project_name}-profile.toml")
    if legacy_path.exists():
        return str(legacy_path)

    if project_name == "install":
        template_root = Path(repo_root).expanduser() if repo_root is not None else _CLAWSEAT_ROOT
        template_path = template_root / "examples" / "starter" / "profiles" / "install-openclaw.toml"
        if template_path.exists():
            dynamic_path.write_text(template_path.read_text(encoding="utf-8"), encoding="utf-8")
            return str(dynamic_path)
        raise FileNotFoundError(
            f"canonical install profile template missing at {template_path}; "
            f"cannot seed /tmp/{project_name}-profile-dynamic.toml"
        )

    # No profile found — need to create one
    raise FileNotFoundError(
        f"no dynamic profile found for project {project_name!r}; "
        f"create /tmp/{project_name}-profile-dynamic.toml from a starter profile "
        f"or run migrate_profile.py if a legacy /tmp/{project_name}-profile.toml already exists"
    )


def init_clawseat_adapter(
    *,
    project_name: str,
    profile_path: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> ClawseatAdapter:
    """
    Initialize a ClawSeatAdapter for the given project.

    ClawSeatAdapter uses repo_root to locate refac/transport/transport_router.py and
    refac/engine/instantiate_seat.py. If repo_root is not provided, defaults to
    _CLAWSEAT_ROOT (the ClawSeat repo root), not the project workspace /tmp/{project}.
    """
    resolved_profile = ensure_clawseat_profile(
        project_name,
        profile_path=profile_path,
    )

    # repo_root must point to the ClawSeat repo root, not the project workspace.
    # ClawSeatAdapter uses repo_root to locate transport_router.py and
    # instantiate_seat.py under refac/ — these resolve correctly when
    # repo_root=_CLAWSEAT_ROOT.
    if repo_root is None:
        repo_root = _CLAWSEAT_ROOT

    resolved_repo = Path(repo_root)
    adapter = ClawseatAdapter(repo_root=resolved_repo)
    adapter.profile_path_for(project_name, resolved_profile)
    return adapter
