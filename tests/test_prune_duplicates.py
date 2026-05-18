"""Poison tests for _do_prune filter-all semantics (T3 bundle-D).

Verifies that _do_prune removes ALL [pending]/[queued] blocks matching the
given task_id, not just the first. These tests would FAIL on the old
first-break implementation.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

from complete_handoff import _do_prune  # noqa: E402


def test_prune_removes_all_duplicates():
    """Two identical [queued] blocks with same task_id — both are removed.

    This test would FAIL under the old first-break implementation since the
    second block would remain.
    """
    block = """\
## [queued] dup-task
task_id: dup-task
title: duplicate entry

### Objective

do something
"""
    content = "# Queue: builder-1\n\n" + block + "\n---\n\n" + block
    result = _do_prune(content, "dup-task")
    assert result is not content
    assert "dup-task" not in result


def test_prune_single_block_still_works():
    """Single matching block is still correctly removed (parity with old behavior)."""
    content = """\
# Queue: builder-1

## [queued] solo-task
task_id: solo-task
title: single entry

### Objective

only one
"""
    result = _do_prune(content, "solo-task")
    assert result is not content
    assert "solo-task" not in result


def test_prune_triple_duplicates():
    """Three copies of the same task_id are all removed."""
    block = """\
## [queued] triple-task
task_id: triple-task
title: triplicate

### Objective

triplicated
"""
    content = "# Queue: builder-1\n\n" + block + "\n---\n\n" + block + "\n---\n\n" + block
    result = _do_prune(content, "triple-task")
    assert result is not content
    assert "triple-task" not in result
    assert "triplicated" not in result


def test_prune_mixed_blocks_other_tasks_intact():
    """Duplicate target task_id removed; other task_ids are untouched."""
    content = """\
# Queue: builder-1

## [queued] keep-task
task_id: keep-task
title: must survive

### Objective

keeper body

---

## [queued] dup-task
task_id: dup-task
title: first dup

### Objective

first dup body

---

## [pending] dup-task
task_id: dup-task
title: second dup

### Objective

second dup body
"""
    result = _do_prune(content, "dup-task")
    assert result is not content
    assert "dup-task" not in result
    assert "first dup body" not in result
    assert "second dup body" not in result
    # other task must be intact
    assert "keep-task" in result
    assert "keeper body" in result


def test_prune_idempotent():
    """Calling _do_prune twice on already-clean text returns same object."""
    content = """\
# Queue: builder-1

## [queued] other-task
task_id: other-task
title: stay

### Objective

body
"""
    first = _do_prune(content, "gone-task")
    assert first is content  # no match, identity returned
    second = _do_prune(first, "gone-task")
    assert second is first  # still no match
