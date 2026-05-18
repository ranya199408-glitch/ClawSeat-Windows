from __future__ import annotations

import json
import os
from types import SimpleNamespace
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import patrol_loop  # noqa: E402


def _write_stale_handoff(home: Path, task_id: str, *, target: str = "builder") -> Path:
    handoffs = home / ".agents" / "tasks" / "demo" / "patrol" / "handoffs"
    handoffs.mkdir(parents=True, exist_ok=True)
    path = handoffs / f"{task_id}__planner__{target}.json"
    path.write_text(
        json.dumps({"task_id": task_id, "source": "planner", "target": target}),
        encoding="utf-8",
    )
    age_hours = patrol_loop.STALE_THRESHOLD_HOURS + 1
    ts = time.time() - age_hours * 3600
    os.utime(path, (ts, ts))
    return path


def test_re_wake_stale_handoffs_sends_once_and_logs(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_stale_handoff(home, "stale-one")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs):
        if cmd[:2] == ["tmux", "capture-pane"]:
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="prompt\n")
        calls.append(cmd)
        return object()

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 1
    assert len(calls) == 2
    assert calls[0] == ["tmux", "capture-pane", "-t", "builder", "-p"]
    assert calls[1][0:4] == [
        "bash",
        str(home / "ClawSeat" / "core" / "shell-scripts" / "send-and-verify.sh"),
        "--project",
        "demo",
    ]
    assert calls[1][4] == "builder"
    assert (
        f"[TASK-QUEUE] 你有未处理的 handoff: stale-one(已 {patrol_loop.STALE_THRESHOLD_HOURS + 1}h)。"
        in calls[1][5]
    )
    assert "请读 TODO.md 头部处理。" in calls[1][5]
    assert "stale-one" in (home / ".agents" / "logs" / "stale-handoff-rewake.log").read_text(encoding="utf-8")

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 0
    assert len(calls) == 2


def test_re_wake_stale_handoffs_caps_each_cycle_at_five(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    for index in range(6):
        _write_stale_handoff(home, f"stale-{index}")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs):
        if cmd[:2] == ["tmux", "capture-pane"]:
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="prompt\n")
        calls.append(cmd)
        return object()

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 5
    assert len(calls) == 10
    send_calls = [call for call in calls if call and call[0] == "bash"]
    assert len(send_calls) == 5


def test_patrol_loop_emits_stale_handoff_marker() -> None:
    text = (SCRIPTS / "patrol_loop.py").read_text(encoding="utf-8")
    assert "[STALE-HANDOFF-REWAKE:project=" in text
