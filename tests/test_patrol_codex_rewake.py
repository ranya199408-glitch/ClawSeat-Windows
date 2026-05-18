from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import patrol_loop  # noqa: E402


def _write_stale_handoff(
    home: Path,
    task_id: str,
    *,
    target: str = "builder",
    age_seconds: int = (patrol_loop.STALE_THRESHOLD_HOURS + 1) * 3600,
) -> Path:
    handoffs = home / ".agents" / "tasks" / "demo" / "patrol" / "handoffs"
    handoffs.mkdir(parents=True, exist_ok=True)
    path = handoffs / f"{task_id}__planner__{target}.json"
    path.write_text(
        json.dumps({"task_id": task_id, "source": "planner", "target": target}),
        encoding="utf-8",
    )
    ts = time.time() - age_seconds
    os.utime(path, (ts, ts))
    return path


def _write_project_toml(home: Path, project: str, engineers: list[str]) -> Path:
    path = home / ".agents" / "projects" / project / "project.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f'name = "{project}"',
                f"engineers = {json.dumps(engineers)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _assert_task_queue_prefix(message: str, task_id: str) -> None:
    assert message.startswith("[TASK-QUEUE] 你有未处理的 handoff: ")
    assert task_id in message
    assert "请读 TODO.md 头部处理。" in message
    assert re.search(r"\(已 \d+h\)", message)


def _cmd_as_text(cmd: list[str] | tuple[str, ...] | str) -> str:
    return " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)


def test_re_wake_codex_working_fresh_handoff_skips_rewake(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_stale_handoff(home, "codex-working", age_seconds=30 * 60)
    calls: list[list[str] | str] = []

    def fake_run(cmd: list[str] | str, **kwargs):
        calls.append(cmd)
        if "capture-pane" in _cmd_as_text(cmd):
            return subprocess.CompletedProcess(cmd, 0, "Working...\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 0
    assert not any("capture-pane" in _cmd_as_text(cmd) for cmd in calls)
    assert not any("send-and-verify.sh" in _cmd_as_text(cmd) for cmd in calls)


def test_re_wake_codex_working_stale_handoff_unblocks_then_sends(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_stale_handoff(home, "codex-working", target="builder")
    calls: list[list[str] | str] = []
    capture_count = 0

    def fake_run(cmd: list[str] | str, **kwargs):
        nonlocal capture_count
        calls.append(cmd)
        text = _cmd_as_text(cmd)
        if "capture-pane" in text:
            capture_count += 1
            output = "Working...\n" if capture_count == 1 else "prompt\n"
            return subprocess.CompletedProcess(cmd, 0, output, "")
        if "send-and-verify.sh" in text:
            return subprocess.CompletedProcess(cmd, 0, "SENT: builder\n", "")
        if "send-keys" in text:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(patrol_loop.time, "sleep", lambda *_: None)

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 1
    send_calls = [cmd for cmd in calls if "send-and-verify.sh" in _cmd_as_text(cmd)]
    assert len(send_calls) == 1
    assert any("send-keys" in _cmd_as_text(cmd) for cmd in calls)
    assert any("capture-pane" in _cmd_as_text(cmd) for cmd in calls)
    log_path = home / ".agents" / "logs" / "seat-unblock.log"
    assert log_path.exists()
    assert "unblock" in log_path.read_text(encoding="utf-8")


def test_re_wake_codex_idle_sends_taskqueue_message(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_stale_handoff(home, "codex-idle")
    calls: list[list[str] | str] = []

    def fake_run(cmd: list[str] | str, **kwargs):
        calls.append(cmd)
        if "capture-pane" in _cmd_as_text(cmd):
            return subprocess.CompletedProcess(cmd, 0, "Previous output\n› \n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 1
    send_calls = [cmd for cmd in calls if "send-and-verify.sh" in _cmd_as_text(cmd)]
    assert len(send_calls) == 1
    send_cmd = send_calls[0]
    sent_message = str(send_cmd[-1]) if isinstance(send_cmd, (list, tuple)) else _cmd_as_text(send_cmd)
    _assert_task_queue_prefix(sent_message, "codex-idle")


def test_re_wake_codex_background_terminal_running_skips_rewake(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_stale_handoff(home, "codex-bg")
    calls: list[list[str] | str] = []

    def fake_run(cmd: list[str] | str, **kwargs):
        calls.append(cmd)
        if "capture-pane" in _cmd_as_text(cmd):
            return subprocess.CompletedProcess(cmd, 0, "background terminal running\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)

    assert patrol_loop.re_wake_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS) == 0
    assert any("capture-pane" in _cmd_as_text(cmd) for cmd in calls)
    assert not any("send-and-verify.sh" in _cmd_as_text(cmd) for cmd in calls)


def test_patrol_seat_health_unblocks_stale_busy_session(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_project_toml(home, "demo", ["builder", "designer", "ghost"])
    _write_stale_handoff(home, "seat-health-builder", target="builder", age_seconds=720)
    sessions = {"demo-builder", "demo-designer"}
    calls: list[list[str] | str] = []
    capture_counts = {"demo-builder": 0}

    def fake_run(cmd: list[str] | str, **kwargs):
        calls.append(cmd)
        text = _cmd_as_text(cmd)
        if cmd[:3] == ["tmux", "list-sessions", "-F"]:
            output = "\n".join(sorted(sessions)) + "\n"
            return subprocess.CompletedProcess(cmd, 0, output, "")
        if cmd[:2] == ["tmux", "capture-pane"]:
            target = str(cmd[3])
            capture_counts[target] = capture_counts.get(target, 0) + 1
            if target == "demo-builder":
                output = "Thinking...\n" if capture_counts[target] == 1 else "prompt\n"
            else:
                output = "prompt\n"
            return subprocess.CompletedProcess(cmd, 0, output, "")
        if cmd[:2] == ["tmux", "send-keys"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "send-and-verify.sh" in text:
            return subprocess.CompletedProcess(cmd, 0, "SENT: demo-builder\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(patrol_loop.subprocess, "run", fake_run)
    monkeypatch.setattr(patrol_loop.time, "sleep", lambda *_: None)

    result = patrol_loop._patrol_seat_health("demo")
    assert result["ok"] == 1
    assert result["blocked"] == 1
    assert result["dead"] == 1
    assert result["summary"] == "[SEAT-HEALTH:project=demo,ok=1,blocked=1,dead=1]"
    assert any("send-keys" in _cmd_as_text(cmd) for cmd in calls)
    assert any("capture-pane" in _cmd_as_text(cmd) for cmd in calls)
    log_path = home / ".agents" / "logs" / "seat-unblock.log"
    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "health_unblock" in log_text
    assert "ghost" in log_text
