"""Tests for T4-A: correlation_id plumbing in dispatch/completion receipts, TODO entries, and DELIVERY.md.

The correlation_id = stable_dispatch_nonce(project, "planning", task_id) — a deterministic 8-char
hex that allows grepping one ID across dispatch receipt, completion receipt, TODO.md, and DELIVERY.md.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from _feishu import stable_dispatch_nonce
from _task_io import append_task_to_queue, write_delivery


# ── helpers ──────────────────────────────────────────────────────────────────

def _expected_cid(project: str = "install", task_id: str = "task-abc") -> str:
    seed = f"{project}:planning:{task_id}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:8]


# ── stable_dispatch_nonce format ─────────────────────────────────────────────


def test_correlation_id_format():
    """stable_dispatch_nonce returns exactly 8 lowercase hex chars."""
    cid = stable_dispatch_nonce("install", "planning", "task-abc")
    assert re.match(r"^[0-9a-f]{8}$", cid), f"Bad format: {cid!r}"


def test_correlation_id_is_deterministic():
    """Same inputs always produce the same correlation_id."""
    a = stable_dispatch_nonce("install", "planning", "task-xyz")
    b = stable_dispatch_nonce("install", "planning", "task-xyz")
    assert a == b


def test_correlation_id_differs_by_task():
    """Different task_ids produce different correlation_ids."""
    a = stable_dispatch_nonce("install", "planning", "task-1")
    b = stable_dispatch_nonce("install", "planning", "task-2")
    assert a != b


# ── append_task_to_queue: correlation_id in TODO.md ──────────────────────────


def test_append_task_injects_correlation_id(tmp_path):
    """append_task_to_queue writes 'correlation_id: <8hex>' line in task header."""
    todo = tmp_path / "TODO.md"
    cid = stable_dispatch_nonce("install", "planning", "task-abc")
    append_task_to_queue(
        todo,
        task_id="task-abc",
        project="install",
        owner="builder-1",
        title="Test task",
        objective="Do something.",
        source="planner",
        reply_to="planner",
        correlation_id=cid,
    )
    text = todo.read_text()
    assert f"correlation_id: {cid}" in text
    assert re.search(r"^correlation_id: [0-9a-f]{8}$", text, re.MULTILINE)


def test_append_task_without_correlation_id_omits_field(tmp_path):
    """append_task_to_queue without correlation_id does not write the field."""
    todo = tmp_path / "TODO.md"
    append_task_to_queue(
        todo,
        task_id="task-no-cid",
        project="install",
        owner="builder-1",
        title="Test task",
        objective="Do something.",
        source="planner",
        reply_to="planner",
    )
    text = todo.read_text()
    assert "correlation_id:" not in text


# ── write_delivery: correlation_id in DELIVERY.md frontmatter ────────────────


def test_write_delivery_injects_correlation_id(tmp_path):
    """write_delivery writes 'correlation_id: <8hex>' in frontmatter."""
    delivery = tmp_path / "DELIVERY.md"
    cid = stable_dispatch_nonce("install", "planning", "task-abc")
    write_delivery(
        delivery,
        task_id="task-abc",
        owner="builder-1",
        target="planner",
        title="Delivery title",
        summary="Work done.",
        status="delivered",
        correlation_id=cid,
    )
    text = delivery.read_text()
    assert f"correlation_id: {cid}" in text
    assert re.search(r"^correlation_id: [0-9a-f]{8}$", text, re.MULTILINE)


def test_write_delivery_without_correlation_id_omits_field(tmp_path):
    """write_delivery without correlation_id does not write the field."""
    delivery = tmp_path / "DELIVERY.md"
    write_delivery(
        delivery,
        task_id="task-no-cid",
        owner="builder-1",
        target="planner",
        title="Delivery title",
        summary="Work done.",
        status="delivered",
    )
    text = delivery.read_text()
    assert "correlation_id:" not in text


# ── cross-receipt consistency ─────────────────────────────────────────────────


def test_correlation_id_matches_across_dispatch_and_completion(tmp_path):
    """Dispatch TODO.md correlation_id matches completion DELIVERY.md correlation_id for same task."""
    todo = tmp_path / "TODO.md"
    delivery = tmp_path / "DELIVERY.md"
    cid = stable_dispatch_nonce("install", "planning", "task-abc")

    append_task_to_queue(
        todo,
        task_id="task-abc",
        project="install",
        owner="builder-1",
        title="Test",
        objective="Do it.",
        source="planner",
        reply_to="planner",
        correlation_id=cid,
    )
    write_delivery(
        delivery,
        task_id="task-abc",
        owner="builder-1",
        target="planner",
        title="Done",
        summary="Done.",
        status="delivered",
        correlation_id=cid,
    )

    todo_match = re.search(r"^correlation_id: ([0-9a-f]{8})$", todo.read_text(), re.MULTILINE)
    delivery_match = re.search(r"^correlation_id: ([0-9a-f]{8})$", delivery.read_text(), re.MULTILINE)
    assert todo_match and delivery_match
    assert todo_match.group(1) == delivery_match.group(1) == cid
