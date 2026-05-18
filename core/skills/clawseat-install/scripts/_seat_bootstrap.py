"""Shared conflict-handling helpers for seat bootstrap scripts.

init_koder.py (frontstage) writes IDENTITY / SOUL / MEMORY (and
TOOLS / AGENTS / WORKSPACE_CONTRACT) into an existing workspace that
OpenClaw or agent_admin has already created. The pre-write conflict
handling lives here.

Public surface:

* ``detect_managed_conflicts(workspace, managed_files)``
* ``backup_managed_files(workspace, conflicts)``
* ``resolve_conflict_policy(policy, conflicts, workspace)``

``managed_files`` is caller-supplied: koder's full set is a superset of the
specialist set.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def detect_managed_conflicts(
    workspace: Path, managed_files: tuple[str, ...] | list[str]
) -> list[str]:
    """Return the subset of ``managed_files`` that already exists in ``workspace``."""
    return [name for name in managed_files if (workspace / name).exists()]


def backup_managed_files(workspace: Path, conflicts: list[str]) -> Path:
    """Move each conflicting managed file into a ``.backup-<ts>/`` subdir.

    Preserves nested layouts (e.g. ``TOOLS/dispatch.md`` → ``.backup-.../TOOLS/dispatch.md``).
    Leaves every non-managed file (skills/, repos/, working artifacts) in place.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = workspace / f".backup-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name in conflicts:
        src = workspace / name
        dst = backup_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    return backup_dir


def resolve_conflict_policy(
    policy: str, conflicts: list[str], workspace: Path
) -> str:
    """For ``--on-conflict=ask``, prompt the operator; otherwise return policy as-is.

    Returns one of ``overwrite`` / ``backup`` / ``abort``.
    """
    if policy != "ask":
        return policy
    print(f"\nworkspace {workspace} already has managed files:")
    for name in conflicts:
        print(f"  • {name}")
    print("\nchoose:")
    print("  1. overwrite  (discard the existing versions in place)")
    print("  2. backup     (move them to .backup-<timestamp>/ then rewrite)")
    print("  3. abort      (do nothing, exit)")
    while True:
        try:
            choice = input("enter 1 / 2 / 3: ").strip()
        except (EOFError, KeyboardInterrupt):
            return "abort"
        if choice == "1":
            return "overwrite"
        if choice == "2":
            return "backup"
        if choice == "3":
            return "abort"
