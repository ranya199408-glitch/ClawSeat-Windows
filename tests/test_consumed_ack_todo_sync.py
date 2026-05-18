"""Tests for _prune_todo_entry / _do_prune in complete_handoff.py (#C1/#C2).

Gate: on --ack-only, the first [pending]/[queued] block matching task_id is
deleted atomically from the ACK target's TODO.md. Status in {in_progress,
completed, abandoned} must NOT be deleted. Fail-safe on IO errors.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

from complete_handoff import _do_prune, _prune_todo_entry  # noqa: E402


# ── Fixtures ────────────────────────────────────────────────────────────────

_ONE_PENDING = """\
# Queue: builder-1

## [pending] my-task
task_id: my-task
title: first
source: planner
reply_to: planner
dispatched_at: 2026-01-01T00:00:00+00:00

### Objective

do something
"""

_TWO_ENTRIES = """\
# Queue: builder-1

## [pending] task-a
task_id: task-a
title: first

### Objective

aaa

---

## [queued] task-b
task_id: task-b
title: second

### Objective

bbb
"""

_THREE_ENTRIES = """\
# Queue: builder-1

## [pending] task-a
task_id: task-a

---

## [queued] task-b
task_id: task-b

---

## [queued] task-c
task_id: task-c
"""

_WITH_COMPLETED = """\
# Queue: builder-1

## [pending] task-live
task_id: task-live

# Completed

- [2026-01-01] task-old
"""

_COMPLETED_ENTRY_NOT_DELETED = """\
# Queue: builder-1

## [completed] my-task
task_id: my-task
title: already done

# Completed

- [2026-01-01] my-task — done
"""


# ── T1: single [pending] block deleted ─────────────────────────────────────


def test_t1_single_pending_block_deleted(tmp_path):
    """[pending] block for task_id is removed; file no longer contains the task."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_ONE_PENDING, encoding="utf-8")
    _prune_todo_entry(todo, "my-task")
    text = todo.read_text(encoding="utf-8")
    assert "my-task" not in text
    assert "## [pending]" not in text


# ── T2: only pending/queued deleted; completed entry preserved ──────────────


def test_t2_only_pending_queued_deleted_completed_preserved(tmp_path):
    """When same task_id appears as [completed] only, no deletion occurs."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_COMPLETED_ENTRY_NOT_DELETED, encoding="utf-8")
    original = todo.read_text(encoding="utf-8")
    _prune_todo_entry(todo, "my-task")
    assert todo.read_text(encoding="utf-8") == original


def test_t2_mixed_statuses_only_first_pending_deleted(tmp_path):
    """File has [pending] task-b and (simulated) completed task-b; only pending deleted."""
    content = """\
# Queue: builder-1

## [pending] task-b
task_id: task-b
title: pending version

---

## [completed] task-a
task_id: task-a

# Completed

- [2026-01-01] task-b — done
"""
    todo = tmp_path / "TODO.md"
    todo.write_text(content, encoding="utf-8")
    _prune_todo_entry(todo, "task-b")
    text = todo.read_text(encoding="utf-8")
    # pending block gone
    assert "## [pending] task-b" not in text
    # completed reference preserved
    assert "task-b — done" in text
    # task-a block intact
    assert "## [completed] task-a" in text


# ── T3: no match → file unchanged ──────────────────────────────────────────


def test_t3_no_match_file_unchanged(tmp_path):
    """When task_id is absent, file bytes are identical after call."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_TWO_ENTRIES, encoding="utf-8")
    before = todo.read_text(encoding="utf-8")
    _prune_todo_entry(todo, "nonexistent-task")
    assert todo.read_text(encoding="utf-8") == before


# ── T4: surrounding entries and separators preserved ───────────────────────


def test_t4_delete_middle_preserves_neighbours(tmp_path):
    """Deleting the middle of three entries keeps the outer two and one separator."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_THREE_ENTRIES, encoding="utf-8")
    _prune_todo_entry(todo, "task-b")
    text = todo.read_text(encoding="utf-8")
    assert "task-a" in text
    assert "task-c" in text
    assert "task-b" not in text
    # exactly one --- separator remains between task-a and task-c
    assert text.count("---") == 1


def test_t4_delete_first_preserves_second(tmp_path):
    """Deleting the first of two entries keeps the second intact."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_TWO_ENTRIES, encoding="utf-8")
    _prune_todo_entry(todo, "task-a")
    text = todo.read_text(encoding="utf-8")
    assert "task-a" not in text
    assert "task-b" in text
    assert "bbb" in text


def test_t4_completed_section_preserved_after_delete(tmp_path):
    """# Completed section is untouched after deleting the live entry."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_WITH_COMPLETED, encoding="utf-8")
    _prune_todo_entry(todo, "task-live")
    text = todo.read_text(encoding="utf-8")
    assert "task-live" not in text
    assert "# Completed" in text
    assert "task-old" in text


# ── T5: missing TODO.md → no-op, no exception ──────────────────────────────


def test_t5_missing_todo_noop(tmp_path):
    """Calling _prune_todo_entry on a non-existent path is a silent no-op."""
    missing = tmp_path / "NOPE.md"
    _prune_todo_entry(missing, "any-task")  # must not raise


# ── T6: IO error → stderr warn, no raise ───────────────────────────────────


def test_t6_io_error_fail_safe(tmp_path, capsys):
    """If reading the TODO.md raises OSError, warn is printed to stderr; no raise."""
    todo = tmp_path / "TODO.md"
    todo.write_text(_ONE_PENDING, encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
        _prune_todo_entry(todo, "my-task")
    captured = capsys.readouterr()
    assert "warn: prune_todo_entry failed" in captured.err
    assert "permission denied" in captured.err


# ── _do_prune unit tests ────────────────────────────────────────────────────


def test_do_prune_returns_same_object_on_no_match():
    """_do_prune returns the same string object when there's nothing to prune."""
    result = _do_prune(_TWO_ENTRIES, "nonexistent")
    assert result is _TWO_ENTRIES


def test_do_prune_deletes_all_matching():
    """When task_id appears under [pending]/[queued] twice, both are deleted."""
    content = """\
# Queue: builder-1

## [pending] task-x
task_id: task-x
title: first occurrence

---

## [queued] task-x
task_id: task-x
title: second occurrence
"""
    result = _do_prune(content, "task-x")
    assert result is not content
    assert "first occurrence" not in result
    assert "second occurrence" not in result
    assert "task-x" not in result


# ── Poison tests: '# Completed' inside entry body must not affect parsing ───


def test_poison_completed_in_objective_body_not_split():
    """A '# Completed' line inside an entry's Objective body must not be treated
    as the trailing section boundary; the entry containing the poison line is
    preserved when a DIFFERENT task_id is deleted."""
    content = """\
# Queue: builder-1

## [queued] safe-task
task_id: safe-task
title: has poison body

### Objective

Some prose.

# Completed

More prose after the poison line.

---

## [pending] target-task
task_id: target-task
title: delete me

### Objective

clean body
"""
    result = _do_prune(content, "target-task")
    assert result is not content
    # target deleted
    assert "target-task" not in result
    assert "delete me" not in result
    # safe-task and its ENTIRE body (including the poison '# Completed' line) preserved
    assert "safe-task" in result
    assert "has poison body" in result
    assert "More prose after the poison line." in result


def test_poison_completed_title_field_entry_deleted():
    """An entry whose *title* field contains '# Completed task' is deleted
    correctly when its task_id is the ACK target; the real trailing
    '# Completed' section (after all ## [ blocks) is preserved."""
    content = """\
# Queue: builder-1

## [pending] poison-title-task
task_id: poison-title-task
title: # Completed task (this is the title)

### Objective

do the thing

# Completed

- [2026-01-01] old-task — done
"""
    result = _do_prune(content, "poison-title-task")
    assert result is not content
    # entry deleted
    assert "poison-title-task" not in result
    assert "do the thing" not in result
    # real trailing section preserved
    assert "# Completed" in result
    assert "old-task — done" in result


# ── Path mapping tests: prune hits source/TODO, not target/TODO ─────────────

_PENDING_ENTRY = """\
# Queue: {seat}

## [queued] task-xyz
task_id: task-xyz
title: some task

### Objective

do stuff
"""


def test_path_source_ack(tmp_path):
    """ACK with source=A target=B must prune A/TODO.md only; B/TODO.md untouched."""
    seat_a = tmp_path / "A"
    seat_b = tmp_path / "B"
    seat_a.mkdir()
    seat_b.mkdir()
    todo_a = seat_a / "TODO.md"
    todo_b = seat_b / "TODO.md"
    todo_a.write_text(_PENDING_ENTRY.format(seat="A"), encoding="utf-8")
    todo_b.write_text(_PENDING_ENTRY.format(seat="B"), encoding="utf-8")

    # Simulate --source A --target B --ack-only: prune source (A) TODO
    _prune_todo_entry(todo_a, "task-xyz")

    assert "task-xyz" not in todo_a.read_text(encoding="utf-8")
    assert "task-xyz" in todo_b.read_text(encoding="utf-8")


@pytest.mark.parametrize("source_seat", ["reviewer-1", "builder-1", "qa-1"])
def test_path_symmetric_planner_target(tmp_path, source_seat):
    """For source=<engineer> target=planner, prune runs on source seat's TODO."""
    source_dir = tmp_path / source_seat
    planner_dir = tmp_path / "planner"
    source_dir.mkdir()
    planner_dir.mkdir()
    source_todo = source_dir / "TODO.md"
    planner_todo = planner_dir / "TODO.md"
    source_todo.write_text(_PENDING_ENTRY.format(seat=source_seat), encoding="utf-8")
    planner_todo.write_text(_PENDING_ENTRY.format(seat="planner"), encoding="utf-8")

    # source seat's TODO is pruned; planner's TODO must not change
    _prune_todo_entry(source_todo, "task-xyz")

    assert "task-xyz" not in source_todo.read_text(encoding="utf-8")
    assert "task-xyz" in planner_todo.read_text(encoding="utf-8")
