"""
Project binding / group management for OpenClaw <-> ClawSeat bridge.

Manages durable project <-> Feishu group bridge bindings via BRIDGE.toml files.
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


# Re-use the shared lock from the main bridge module.
# Imported lazily to avoid circular imports during module init.
def _get_binding_lock() -> threading.RLock:
    from openclaw_bridge import _BRIDGE_BINDING_LOCK
    return _BRIDGE_BINDING_LOCK


def _projects_root() -> Path:
    return Path(os.path.expanduser("~/.agents/projects"))


def _bridge_path_for_project(project: str) -> Path:
    return _projects_root() / project / "BRIDGE.toml"


def _bridge_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _quote_toml(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _load_bridge_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    bridge = payload.get("bridge")
    if not isinstance(bridge, dict):
        return None
    return {
        "project": str(bridge.get("project", "")).strip(),
        "group_id": str(bridge.get("group_id", "")).strip(),
        "account_id": str(bridge.get("account_id", "")).strip(),
        "session_key": str(bridge.get("session_key", "")).strip(),
        "bridge_mode": str(bridge.get("bridge_mode", "")).strip(),
        "bound_at": str(bridge.get("bound_at", "")).strip(),
        "bound_by": str(bridge.get("bound_by", "")).strip(),
        "bridge_path": str(path),
    }


def _assert_parent_is_not_symlink(path: Path) -> None:
    """Guard against a symlink-race attack on `~/.agents/projects/<proj>/`.

    An attacker who can write under `~/.agents/projects/` before ClawSeat
    creates a project directory could turn `projects/<proj>` into a
    symlink pointing outside the expected tree; a subsequent
    ``parent.mkdir(parents=True)`` would happily follow it and
    ``os.replace(..., path)`` would then drop the BRIDGE.toml at the
    symlink target (e.g. ``/etc/BRIDGE.toml`` if ClawSeat runs as root).
    Audit L10.

    Check the full chain up to `_projects_root()` — any symlinked
    component means "not mine", reject.
    """
    # Only ancestors that already exist matter; unresolved ancestors will
    # be created by `mkdir(parents=True)` below and can't be symlinks.
    root = _projects_root().resolve()
    probe = path.parent
    while probe != probe.parent:
        try:
            if probe.is_symlink():
                raise RuntimeError(
                    f"refusing to write through symlinked component {probe}; "
                    "this would escape ~/.agents/projects/ (audit L10)"
                )
        except OSError:
            # Path doesn't exist yet — nothing to verify up the chain.
            break
        if probe.resolve(strict=False) == root:
            break
        probe = probe.parent


def _write_bridge_file(path: Path, binding: dict[str, Any]) -> None:
    _assert_parent_is_not_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[bridge]",
        f"project = {_quote_toml(binding['project'])}",
        f"group_id = {_quote_toml(binding['group_id'])}",
        f"account_id = {_quote_toml(binding['account_id'])}",
        f"session_key = {_quote_toml(binding['session_key'])}",
        f'bridge_mode = "user_identity"',
        f"bound_at = {_quote_toml(binding['bound_at'])}",
        f"bound_by = {_quote_toml(binding['bound_by'])}",
        "",
    ]
    fd, tmp_path = tempfile.mkstemp(prefix="bridge-", suffix=".toml", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _collect_project_bindings() -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    root = _projects_root()
    if not root.exists():
        return bindings
    for bridge_path in sorted(root.glob("*/BRIDGE.toml")):
        binding = _load_bridge_file(bridge_path)
        if binding is None:
            continue
        bindings.append(binding)
    return bindings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_project_bindings() -> list[dict[str, Any]]:
    """
    List all durable project <-> group bridge bindings.
    """
    with _get_binding_lock():
        return _collect_project_bindings()


def get_binding_for_group(group_id: str) -> dict[str, Any] | None:
    """
    Return the durable binding for a Feishu group id, if any.
    """
    resolved_group_id = str(group_id).strip()
    if not resolved_group_id:
        raise ValueError("group_id is required")
    with _get_binding_lock():
        for binding in _collect_project_bindings():
            if binding["group_id"] == resolved_group_id:
                return binding
    return None


def bind_project_to_group(
    project: str,
    group_id: str,
    account_id: str,
    session_key: str,
    bound_by: str,
    *,
    authorized: bool = False,
) -> dict[str, Any]:
    """
    Bind one project to one Feishu group with explicit user authorization.

    Constraints:
    - one project -> one group
    - one group -> one project
    """
    resolved_project = str(project).strip()
    resolved_group_id = str(group_id).strip()
    resolved_account_id = str(account_id).strip()
    resolved_session_key = str(session_key).strip()
    resolved_bound_by = str(bound_by).strip()

    if not authorized:
        raise PermissionError("bind_project_to_group requires explicit authorized=True")
    if not resolved_project:
        raise ValueError("project is required")
    if not resolved_group_id:
        raise ValueError("group_id is required")
    if not resolved_account_id:
        raise ValueError("account_id is required")
    if not resolved_session_key:
        raise ValueError("session_key is required")
    if not resolved_bound_by:
        raise ValueError("bound_by is required")

    with _get_binding_lock():
        bindings = _collect_project_bindings()
        for binding in bindings:
            if binding["group_id"] == resolved_group_id and binding["project"] != resolved_project:
                raise ValueError(
                    f"group {resolved_group_id!r} is already bound to project {binding['project']!r}"
                )
            if binding["project"] == resolved_project and binding["group_id"] != resolved_group_id:
                raise ValueError(
                    f"project {resolved_project!r} is already bound to group {binding['group_id']!r}"
                )

        binding = {
            "project": resolved_project,
            "group_id": resolved_group_id,
            "account_id": resolved_account_id,
            "session_key": resolved_session_key,
            "bridge_mode": "user_identity",
            "bound_at": _bridge_now_iso(),
            "bound_by": resolved_bound_by,
        }
        path = _bridge_path_for_project(resolved_project)
        _write_bridge_file(path, binding)
        binding["bridge_path"] = str(path)
        return binding


def unbind_project(project: str) -> dict[str, Any] | None:
    """
    Remove the durable bridge binding for a project.
    """
    resolved_project = str(project).strip()
    if not resolved_project:
        raise ValueError("project is required")
    with _get_binding_lock():
        path = _bridge_path_for_project(resolved_project)
        binding = _load_bridge_file(path)
        if binding is None:
            return None
        path.unlink(missing_ok=True)
        return binding
