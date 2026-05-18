from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import liveness_gate  # noqa: E402


def test_restart_seat_uses_window_open_engineer(monkeypatch) -> None:
    """restart_seat must call window open-engineer, not session start-engineer."""
    calls: list[list[str]] = []

    def mock_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(
        liveness_gate,
        "query_seat_liveness",
        lambda *args, **kwargs: [{"role": "builder", "status": "alive"}],
    )

    assert liveness_gate.restart_seat("install", "builder") is True
    assert any("window" in call and "open-engineer" in call for call in calls), calls
    assert not any("session" in call and "start-engineer" in call for call in calls), calls
