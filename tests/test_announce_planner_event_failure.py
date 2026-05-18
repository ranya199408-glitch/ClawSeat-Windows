"""
Tests for _try_announce_planner_event failure transparency in dispatch_task.py
and complete_handoff.py (T3 bundle-C).

Covers: exception path, failed-status warn, sent-status silent, skipped-status silent,
and payload return contract.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "core/skills/gstack-harness/scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import dispatch_task
import complete_handoff

_COMMON_KWARGS = dict(project="install", source="planner", target="builder-1", task_id="task-xyz", verb="dispatched")


def _feishu_mock(return_value=None, side_effect=None):
    mock_send = MagicMock(return_value=return_value, side_effect=side_effect)
    return {"_feishu": MagicMock(send_feishu_user_message=mock_send)}


# ── dispatch_task ─────────────────────────────────────────────────────────────


def test_dispatch_announce_exception_prints_warn(capsys):
    with patch.dict("sys.modules", _feishu_mock(side_effect=RuntimeError("conn refused"))):
        result = dispatch_task._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert "planner announce failed" in err
    assert result["status"] == "exception"


def test_dispatch_announce_failed_status_prints_warn(capsys):
    with patch.dict("sys.modules", _feishu_mock(return_value={"status": "failed", "reason": "auth_expired"})):
        result = dispatch_task._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert "planner announce feishu returned" in err
    assert result["status"] == "failed"


def test_dispatch_announce_sent_status_silent(capsys):
    with patch.dict("sys.modules", _feishu_mock(return_value={"status": "sent"})):
        result = dispatch_task._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert err == ""
    assert result["status"] == "sent"


def test_dispatch_announce_skipped_status_silent(capsys):
    with patch.dict("sys.modules", _feishu_mock(return_value={"status": "skipped", "reason": "no_group_id_found"})):
        result = dispatch_task._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert err == ""
    assert result["status"] == "skipped"


def test_dispatch_announce_returns_payload(capsys):
    payload = {"status": "sent", "msg_id": "abc123"}
    with patch.dict("sys.modules", _feishu_mock(return_value=payload)):
        result = dispatch_task._try_announce_planner_event(**_COMMON_KWARGS)
    assert result == payload


# ── complete_handoff ──────────────────────────────────────────────────────────


def test_handoff_announce_exception_prints_warn(capsys):
    with patch.dict("sys.modules", _feishu_mock(side_effect=RuntimeError("timeout"))):
        result = complete_handoff._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert "planner announce failed" in err
    assert result["status"] == "exception"


def test_handoff_announce_failed_status_prints_warn(capsys):
    with patch.dict("sys.modules", _feishu_mock(return_value={"status": "failed", "stderr": "403 Forbidden"})):
        result = complete_handoff._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert "planner announce feishu returned" in err
    assert result["status"] == "failed"


def test_handoff_announce_sent_status_silent(capsys):
    with patch.dict("sys.modules", _feishu_mock(return_value={"status": "sent"})):
        result = complete_handoff._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert err == ""


def test_handoff_announce_skipped_status_silent(capsys):
    with patch.dict("sys.modules", _feishu_mock(return_value={"status": "skipped"})):
        result = complete_handoff._try_announce_planner_event(**_COMMON_KWARGS)
    err = capsys.readouterr().err
    assert err == ""


def test_handoff_announce_returns_payload(capsys):
    payload = {"status": "sent", "msg_id": "def456"}
    with patch.dict("sys.modules", _feishu_mock(return_value=payload)):
        result = complete_handoff._try_announce_planner_event(**_COMMON_KWARGS)
    assert result == payload
