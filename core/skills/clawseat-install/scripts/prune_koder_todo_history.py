"""prune_koder_todo_history.py — one-time migration to clean stale AUTO_ADVANCE
entries from koder TODO.md files.

Usage:
    python3 prune_koder_todo_history.py [--project install|hardening-b|all] \
        [--dry-run] [--yes]

Default mode is dry-run (no file changes). Pass --yes to write.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── path resolution ───────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT / "core" / "lib") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "core" / "lib"))
from real_home import real_user_home

_AGENTS_ROOT = Path(os.environ.get("AGENTS_ROOT", str(real_user_home() / ".agents")))
_IDENTITIES_ROOT = _AGENTS_ROOT / "runtime" / "identities"

_HANDOFFS_GLOB_PATTERN = "patrol/handoffs"


def _handoffs_dir_for_project(identities_root: Path, project: str) -> list[Path]:
    """Find patrol/handoffs dirs for all koder identities for the given project."""
    if not identities_root.exists():
        return []
    results = list(identities_root.rglob(f"home/.agents/tasks/{project}/patrol/handoffs"))
    return [p for p in results if p.is_dir()]


def _find_koder_todo_paths(identities_root: Path, project: str) -> list[Path]:
    """Locate koder TODO.md files for the given project."""
    glob_override = os.environ.get("CLAWSEAT_KODER_TODO_GLOB")
    if glob_override:
        return list(identities_root.glob(glob_override))

    if not identities_root.exists():
        return []
    return list(identities_root.rglob(f"home/.agents/tasks/{project}/koder/TODO.md"))


# ── TODO.md parsing ───────────────────────────────────────────────────────────

_BLOCK_RE = re.compile(r"(?m)^(?=## \[)")
_CONSUMED_TASK_ID_RE = re.compile(r"Consumed:\s+(\S+)\s+from\s+planner")
_TASK_ID_FIELD_RE = re.compile(r"^task_id:\s+(\S+)", re.MULTILINE)


def _parse_blocks(text: str) -> list[str]:
    """Split TODO.md into blocks. Block 0 is the file header (before first ## [)."""
    parts = _BLOCK_RE.split(text)
    return parts


def _task_id_from_block(block: str) -> str | None:
    m = _TASK_ID_FIELD_RE.search(block)
    return m.group(1) if m else None


def _consumed_task_id_from_block(block: str) -> str | None:
    m = _CONSUMED_TASK_ID_RE.search(block)
    return m.group(1) if m else None


# ── stale detection ───────────────────────────────────────────────────────────

def _is_stale(task_id: str, handoffs_dirs: list[Path]) -> bool:
    """Return True if task_id has a planner→koder handoff AND a consumed ACK."""
    if not task_id:
        return False
    for hdir in handoffs_dirs:
        # planner sent the closeout
        sent_pat = f"{task_id}__planner__koder.json"
        consumed_pat = f"{task_id}__planner__koder__consumed.json"
        if (hdir / sent_pat).exists() and (hdir / consumed_pat).exists():
            return True
    return False


# ── main prune logic ──────────────────────────────────────────────────────────

def prune_todo(
    todo_path: Path,
    handoffs_dirs: list[Path],
    *,
    dry_run: bool = True,
) -> dict:
    """Prune stale entries from a koder TODO.md.

    Returns a dict: {stale_count, total_blocks, written, backup_path}.
    """
    text = todo_path.read_text(encoding="utf-8")
    blocks = _parse_blocks(text)

    stale_indices: list[int] = []
    for i, block in enumerate(blocks):
        if i == 0:
            continue  # file header
        task_id = _task_id_from_block(block) or _consumed_task_id_from_block(block)
        if task_id and _is_stale(task_id, handoffs_dirs):
            stale_indices.append(i)

    result = {
        "stale_count": len(stale_indices),
        "total_blocks": len(blocks) - 1,  # exclude header
        "written": False,
        "backup_path": None,
    }

    if stale_indices:
        if dry_run:
            print(f"[dry-run] {todo_path}: would remove {len(stale_indices)} stale block(s)")
            for i in stale_indices:
                task_id = _task_id_from_block(blocks[i]) or _consumed_task_id_from_block(blocks[i]) or "?"
                print(f"  - block {i}: task_id={task_id}")
        else:
            kept = [block for i, block in enumerate(blocks) if i not in stale_indices]
            new_text = "".join(kept)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = todo_path.with_suffix(f".prune-{stamp}.bak")
            backup_path.write_text(text, encoding="utf-8")
            todo_path.write_text(new_text, encoding="utf-8")
            result["written"] = True
            result["backup_path"] = str(backup_path)
            print(f"pruned {len(stale_indices)} stale block(s) from {todo_path} (backup: {backup_path})")
    else:
        print(f"{'[dry-run] ' if dry_run else ''}{todo_path}: no stale entries found")

    return result


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", default="all", help="Project to prune (install|hardening-b|all). Default: all.")
    p.add_argument("--dry-run", action="store_true", default=True, help="Print changes without writing (default).")
    p.add_argument("--yes", action="store_true", help="Write pruned files (overrides --dry-run).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None, *, identities_root: Path | None = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.yes

    root = identities_root or _IDENTITIES_ROOT
    projects = ["install", "hardening-b"] if args.project == "all" else [args.project]

    any_io_error = False
    for project in projects:
        todo_paths = _find_koder_todo_paths(root, project)
        if not todo_paths:
            print(f"no koder TODO.md found for project={project}", file=sys.stderr)
            continue
        handoffs_dirs = _handoffs_dir_for_project(root, project)
        for todo_path in todo_paths:
            try:
                prune_todo(todo_path, handoffs_dirs, dry_run=dry_run)
            except OSError as exc:
                print(f"error: {todo_path}: {exc}", file=sys.stderr)
                any_io_error = True

    return 1 if any_io_error else 0


if __name__ == "__main__":
    sys.exit(main())
