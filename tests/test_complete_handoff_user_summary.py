"""Tests for build_completion_message --user-summary concatenation (#5).

Coverage:
  - build_completion_message without user_summary produces baseline message
  - build_completion_message with user_summary appends it to the message
  - user_summary is stripped before appending
  - user_summary=None is treated same as omitted
  - user_summary="" (empty string) is treated as absent (not appended)
  - message still contains task_id, source, target, delivery_path
  - user_summary with whitespace-only is treated as absent
  - multiple spaces in user_summary are preserved (not over-stripped)
"""
from __future__ import annotations

from pathlib import Path
import sys

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from _task_io import build_completion_message  # noqa: E402


_DELIVERY = Path("/tmp/test/DELIVERY.md")


def test_baseline_no_user_summary():
    msg = build_completion_message("T-001", _DELIVERY, source="builder-1", target="planner")
    assert "T-001" in msg
    assert "builder-1" in msg
    assert "planner" in msg
    assert str(_DELIVERY) in msg
    assert "UserSummary" not in msg


def test_user_summary_appended_to_message():
    msg = build_completion_message(
        "T-002", _DELIVERY, source="builder-1", target="planner", user_summary="All tests pass."
    )
    assert "UserSummary: All tests pass." in msg


def test_user_summary_stripped():
    msg = build_completion_message(
        "T-003", _DELIVERY, source="builder-1", target="planner", user_summary="  trimmed  "
    )
    assert "UserSummary: trimmed" in msg
    assert "UserSummary:   trimmed" not in msg


def test_user_summary_none_omitted():
    msg = build_completion_message(
        "T-004", _DELIVERY, source="builder-1", target="planner", user_summary=None
    )
    assert "UserSummary" not in msg


def test_user_summary_empty_string_omitted():
    msg = build_completion_message(
        "T-005", _DELIVERY, source="builder-1", target="planner", user_summary=""
    )
    assert "UserSummary" not in msg


def test_user_summary_whitespace_only_omitted():
    msg = build_completion_message(
        "T-006", _DELIVERY, source="builder-1", target="planner", user_summary="   "
    )
    assert "UserSummary" not in msg


def test_message_contains_task_id_with_summary():
    msg = build_completion_message(
        "T-007", _DELIVERY, source="qa-1", target="planner", user_summary="smoke passed"
    )
    assert "T-007" in msg
    assert "qa-1" in msg
    assert "planner" in msg


def test_user_summary_internal_spaces_preserved():
    msg = build_completion_message(
        "T-008", _DELIVERY, source="reviewer-1", target="planner",
        user_summary="fix A, fix B, fix C"
    )
    assert "fix A, fix B, fix C" in msg


def test_consumed_ack_instruction_present_with_summary():
    msg = build_completion_message(
        "T-009", _DELIVERY, source="builder-1", target="planner", user_summary="done"
    )
    assert "Consumed ACK" in msg


def test_consumed_ack_instruction_present_without_summary():
    msg = build_completion_message("T-010", _DELIVERY, source="builder-1", target="planner")
    assert "Consumed ACK" in msg
