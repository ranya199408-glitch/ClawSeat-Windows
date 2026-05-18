"""Tests for T16 Item 4: prune_koder_todo_history.py migration script.

Covers:
  5. test_dry_run_identifies_stale_entries
  6. test_yes_flag_prunes_and_backs_up
  7. test_idempotent_second_run_noop
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "core" / "skills" / "clawseat-install" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import prune_koder_todo_history as pkt


# ── fixture helpers ───────────────────────────────────────────────────────────

_HEADER = "# Queue: koder\n\n"

_STALE_BLOCK_1 = """\
## [completed] task-alpha
task_id: task-alpha
title: Alpha task
dispatched_at: 2026-04-01T00:00:00+00:00

Alpha content.

"""

_STALE_BLOCK_2 = """\
## [completed] task-beta
task_id: task-beta
title: Beta task
dispatched_at: 2026-04-02T00:00:00+00:00

Beta content.

"""

_LIVE_BLOCK = """\
## [queued] task-gamma
task_id: task-gamma
title: Gamma task — live, not consumed yet
dispatched_at: 2026-04-03T00:00:00+00:00

Gamma content.

"""


def _make_todo(tmp_path: Path, blocks: list[str]) -> Path:
    todo = tmp_path / "TODO.md"
    todo.write_text(_HEADER + "".join(blocks), encoding="utf-8")
    return todo


def _make_handoffs(tmp_path: Path, *task_ids: str) -> Path:
    hdir = tmp_path / "handoffs"
    hdir.mkdir(parents=True, exist_ok=True)
    for tid in task_ids:
        (hdir / f"{tid}__planner__koder.json").write_text(json.dumps({"task_id": tid}))
        (hdir / f"{tid}__planner__koder__consumed.json").write_text(json.dumps({"task_id": tid}))
    return hdir


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: dry-run identifies stale entries, does not modify TODO.md
# ══════════════════════════════════════════════════════════════════════════════

def test_dry_run_identifies_stale_entries(tmp_path, capsys):
    todo = _make_todo(tmp_path, [_STALE_BLOCK_1, _STALE_BLOCK_2, _LIVE_BLOCK])
    original_text = todo.read_text(encoding="utf-8")
    handoffs = _make_handoffs(tmp_path, "task-alpha", "task-beta")

    result = pkt.prune_todo(todo, [handoffs], dry_run=True)

    assert result["stale_count"] == 2
    # File must not be modified
    assert todo.read_text(encoding="utf-8") == original_text
    out = capsys.readouterr().out
    assert "task-alpha" in out or "2" in out


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: --yes prunes stale entries, creates backup, retains live entry
# ══════════════════════════════════════════════════════════════════════════════

def test_yes_flag_prunes_and_backs_up(tmp_path):
    todo = _make_todo(tmp_path, [_STALE_BLOCK_1, _STALE_BLOCK_2, _LIVE_BLOCK])
    handoffs = _make_handoffs(tmp_path, "task-alpha", "task-beta")

    result = pkt.prune_todo(todo, [handoffs], dry_run=False)

    assert result["written"] is True
    assert result["backup_path"] is not None
    bak = Path(result["backup_path"])
    assert bak.exists(), "backup file should exist"

    new_text = todo.read_text(encoding="utf-8")
    assert "task-gamma" in new_text
    assert "task-alpha" not in new_text
    assert "task-beta" not in new_text


# ══════════════════════════════════════════════════════════════════════════════
# Test 7: idempotent — second run finds no stale entries to prune
# ══════════════════════════════════════════════════════════════════════════════

def test_idempotent_second_run_noop(tmp_path):
    todo = _make_todo(tmp_path, [_STALE_BLOCK_1, _LIVE_BLOCK])
    handoffs = _make_handoffs(tmp_path, "task-alpha")

    # First run prunes task-alpha
    result1 = pkt.prune_todo(todo, [handoffs], dry_run=False)
    assert result1["stale_count"] == 1
    text_after_first = todo.read_text(encoding="utf-8")

    # Second run: no stale entries remain
    result2 = pkt.prune_todo(todo, [handoffs], dry_run=False)
    assert result2["stale_count"] == 0
    assert result2["written"] is False
    # File unchanged
    assert todo.read_text(encoding="utf-8") == text_after_first


# ══════════════════════════════════════════════════════════════════════════════
# Test 8 (F1 regression): default discovery walks nested identity layout
# ══════════════════════════════════════════════════════════════════════════════

def test_default_discovery_walks_nested_identity_layout(tmp_path, monkeypatch):
    """rglob-based discovery finds TODO.md at real 4-level-deep identity path.

    Layout mirrors production:
      identities/<tool>/<auth_mode>/<full-identity>/<sandbox-home>/tasks/<project>/koder/TODO.md
    """
    task_id = "nested-task-001"
    project = "install"

    # Build nested identity tree
    identity_base = (
        tmp_path / "runtime" / "identities"
        / "claude" / "oauth" / "claude.oauth.anthropic.install.planner"
        / "home" / ".agents" / "tasks" / project
    )
    koder_dir = identity_base / "koder"
    koder_dir.mkdir(parents=True)

    # Seed TODO.md with one stale block
    todo_path = koder_dir / "TODO.md"
    stale_block = (
        f"## [completed] {task_id}\n"
        f"task_id: {task_id}\n"
        "title: Nested stale task\n\n"
        "Some content.\n\n"
    )
    todo_path.write_text(_HEADER + stale_block, encoding="utf-8")

    # Seed consumed handoff files in patrol/handoffs (also nested)
    handoffs_dir = identity_base / "patrol" / "handoffs"
    handoffs_dir.mkdir(parents=True)
    import json as _json
    (handoffs_dir / f"{task_id}__planner__koder.json").write_text(_json.dumps({"task_id": task_id}))
    (handoffs_dir / f"{task_id}__planner__koder__consumed.json").write_text(_json.dumps({"task_id": task_id}))

    # Ensure env override is NOT set so rglob path is exercised
    monkeypatch.delenv("CLAWSEAT_KODER_TODO_GLOB", raising=False)

    identities_root = tmp_path / "runtime" / "identities"
    rc = pkt.main(["--project", project, "--yes"], identities_root=identities_root)

    assert rc == 0
    pruned_text = todo_path.read_text(encoding="utf-8")
    assert task_id not in pruned_text, "stale block should have been pruned"
    bak_files = list(koder_dir.glob("*.bak"))
    assert bak_files, "backup .bak file should have been created"
