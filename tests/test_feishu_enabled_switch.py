"""Regression tests for CLAWSEAT_FEISHU_ENABLED=0 global Feishu skip switch.

Covers the three main send paths:
1. send_delegation_report.py early-exit
2. _feishu.send_feishu_user_message returns {"status": "skipped"}
3. _feishu.broadcast_feishu_group_message returns {"status": "skipped"}
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

SEND_REPORT = _SCRIPTS / "send_delegation_report.py"


# ── send_delegation_report.py ─────────────────────────────────────────────────

def test_send_delegation_report_skips_when_feishu_disabled(tmp_path):
    """CLAWSEAT_FEISHU_ENABLED=0 → exit 0, JSON status=skipped."""
    env = {**os.environ, "CLAWSEAT_FEISHU_ENABLED": "0"}
    result = subprocess.run(
        [sys.executable, str(SEND_REPORT), "--project", "install", "--dry-run"],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert '"status": "skipped"' in result.stdout
    assert "CLAWSEAT_FEISHU_ENABLED=0" in result.stdout


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_send_delegation_report_runs_normally_when_feishu_enabled(tmp_path):
    """Without CLAWSEAT_FEISHU_ENABLED=0, dry-run proceeds normally."""
    env = {k: v for k, v in os.environ.items() if k != "CLAWSEAT_FEISHU_ENABLED"}
    env["CLAWSEAT_FEISHU_GROUP_ID"] = "<FEISHU_GROUP_ID>"
    result = subprocess.run(
        [sys.executable, str(SEND_REPORT), "--project", "install", "--dry-run"],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "OC_DELEGATION_REPORT_V1" in result.stdout
    assert "skipped" not in result.stdout


# ── _feishu.send_feishu_user_message ─────────────────────────────────────────

def test_send_feishu_user_message_skips_when_disabled(monkeypatch):
    """send_feishu_user_message returns skipped dict when FEISHU disabled."""
    monkeypatch.setenv("CLAWSEAT_FEISHU_ENABLED", "0")
    from _feishu import send_feishu_user_message
    result = send_feishu_user_message("hello", project="test")
    assert result.get("status") == "skipped"
    assert "CLAWSEAT_FEISHU_ENABLED=0" in result.get("reason", "")


# ── _feishu.broadcast_feishu_group_message ────────────────────────────────────

def test_broadcast_feishu_group_message_skips_when_disabled(monkeypatch):
    """broadcast_feishu_group_message returns skipped dict when FEISHU disabled."""
    monkeypatch.setenv("CLAWSEAT_FEISHU_ENABLED", "0")
    from _feishu import broadcast_feishu_group_message
    result = broadcast_feishu_group_message("hello", project="test")
    assert result.get("status") == "skipped"
    assert "CLAWSEAT_FEISHU_ENABLED=0" in result.get("reason", "")
