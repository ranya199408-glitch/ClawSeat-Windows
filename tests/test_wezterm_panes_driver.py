from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import wezterm_panes_driver as driver


def _result(args: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_panes_layout_returns_error_when_send_text_fails(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_wezterm_cli(args: list[str], timeout: float = driver.BUILD_TIMEOUT_SECONDS):
        calls.append(args)
        if args[:1] == ["spawn"]:
            return _result(args, stdout="101\n")
        if args[:2] == ["list", "--format"]:
            return _result(args, stdout='[{"pane_id": "101", "window_id": "w1"}]')
        if args[:1] == ["send-text"]:
            return _result(args, returncode=1, stderr="send failed")
        return _result(args)

    monkeypatch.setattr(driver, "wezterm_cli", fake_wezterm_cli)

    result = driver._build_panes_layout(
        {
            "title": "clawseat-test",
            "panes": [{"label": "memory", "command": "tmux attach -t memory"}],
            "send_delay_ms": 0,
        }
    )

    assert result["status"] == "error"
    assert "send-text" in result["reason"]
    assert ["kill-window", "--window-id", "w1"] in calls


def test_tabs_layout_returns_error_when_tab_spawn_fails(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_wezterm_cli(args: list[str], timeout: float = driver.BUILD_TIMEOUT_SECONDS):
        calls.append(args)
        if args[:1] == ["spawn"] and "--window-id" not in args:
            return _result(args, stdout="201\n")
        if args[:2] == ["list", "--format"]:
            return _result(args, stdout='[{"pane_id": "201", "window_id": "w2"}]')
        if args[:1] == ["send-text"]:
            return _result(args)
        if args[:1] == ["spawn"] and "--window-id" in args:
            return _result(args, returncode=1, stderr="tab failed")
        return _result(args)

    monkeypatch.setattr(driver, "wezterm_cli", fake_wezterm_cli)

    result = driver._build_tabs_layout(
        {
            "mode": "tabs",
            "title": "clawseat-memories",
            "tabs": [
                {"name": "project-a", "command": "tmux attach -t project-a"},
                {"name": "project-b", "command": "tmux attach -t project-b"},
            ],
            "send_delay_ms": 0,
        }
    )

    assert result["status"] == "error"
    assert "tab 1" in result["reason"]
    assert ["kill-window", "--window-id", "w2"] in calls
