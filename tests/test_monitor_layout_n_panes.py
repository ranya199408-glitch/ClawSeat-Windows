"""Tests for build_monitor_layout with > 4 visible engineers.

Pre-existing behavior only handled 1-4 panes — engineers #5, #6, … were
silently dropped. This guards the extension that splits the largest pane
for each extra seat so up to monitor_max_panes engineers all get a tile.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

import agent_admin_window


def _make_project(*, n: int, mode: str = "project-monitor") -> SimpleNamespace:
    engineer_ids = [f"seat{i}" for i in range(n)]
    return SimpleNamespace(
        name="demo",
        repo_root="/tmp/demo-repo",
        monitor_session="project-demo-monitor",
        monitor_engineers=engineer_ids,
        engineers=engineer_ids,
        monitor_max_panes=n,
        window_mode=mode,
    )


def _make_sessions(n: int) -> dict[str, SimpleNamespace]:
    return {
        f"seat{i}": SimpleNamespace(
            engineer_id=f"seat{i}",
            session=f"demo-seat{i}",
            workspace=f"/tmp/ws{i}",
        )
        for i in range(n)
    }


class _FakeTmux:
    """Records every tmux invocation; simulates list-panes after splits."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        # Initial single pane — width/height arbitrary
        self.panes: list[dict[str, int | str]] = [
            {"pane_id": "%0", "width": 240, "height": 80, "left": 0, "top": 0}
        ]

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        verb = args[0] if args else ""
        stdout = ""
        # Simulate new-session -P -F '#{pane_id}' returning the first pane id.
        if verb == "new-session" and "-P" in args:
            stdout = self.panes[0]["pane_id"]
        # Simulate split-window by halving the targeted pane and (if -P -F)
        # returning the new pane id on stdout.
        if verb == "split-window":
            target = None
            direction = None
            for i, a in enumerate(args):
                if a == "-t" and i + 1 < len(args):
                    target = args[i + 1]
                if a in ("-h", "-v"):
                    direction = a
            for i, p in enumerate(self.panes):
                if p["pane_id"] == target:
                    new_id = f"%{len(self.panes)}"
                    if direction == "-h":
                        new_w = int(p["width"]) // 2
                        p["width"] = new_w
                        new_pane = {
                            "pane_id": new_id,
                            "width": new_w,
                            "height": p["height"],
                            "left": int(p["left"]) + new_w,
                            "top": p["top"],
                        }
                    else:
                        new_h = int(p["height"]) // 2
                        p["height"] = new_h
                        new_pane = {
                            "pane_id": new_id,
                            "width": p["width"],
                            "height": new_h,
                            "left": p["left"],
                            "top": int(p["top"]) + new_h,
                        }
                    self.panes.append(new_pane)
                    if "-P" in args:
                        stdout = new_id
                    break
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def _install_fakes(monkeypatch, fake: _FakeTmux):
    monkeypatch.setattr(agent_admin_window, "tmux_with_retry", fake)
    # engineer sessions exist; monitor session doesn't (skip kill-before-create)
    monkeypatch.setattr(
        agent_admin_window,
        "tmux_has_session",
        lambda s: s.startswith("demo-seat"),
    )
    monkeypatch.setattr(
        agent_admin_window,
        "tmux_window_panes",
        lambda _target: list(fake.panes),
    )


def _split_count(calls: list[list[str]]) -> int:
    return sum(1 for c in calls if c and c[0] == "split-window")


def _attach_targets(calls: list[list[str]]) -> list[str]:
    """Extract the session name being attached in each split or send-keys."""
    targets = []
    for c in calls:
        if not c:
            continue
        # The attach command is a positional arg shaped like:
        #   "tmux attach -t demo-seatN" or wrapped in a shell command
        for token in c:
            if "demo-seat" in token:
                # find the first "demo-seatN"
                for word in token.split():
                    word = word.strip("'\";")
                    if word.startswith("demo-seat"):
                        targets.append(word)
                        break
                break
    return targets


def test_build_monitor_layout_six_panes_creates_five_splits(monkeypatch):
    """6 engineers → 1 send-keys + 5 split-window calls (engineers #2..#6)."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=6)
    sessions = _make_sessions(6)

    agent_admin_window.build_monitor_layout(project, sessions)

    assert _split_count(fake.calls) == 5, (
        f"6 engineers should produce 5 splits, got {_split_count(fake.calls)}"
    )
    targets = _attach_targets(fake.calls)
    expected = [f"demo-seat{i}" for i in range(6)]
    assert sorted(set(targets)) == sorted(expected), (
        f"all 6 engineer sessions must be attached; got {targets}"
    )


def test_build_monitor_layout_six_panes_runs_select_layout_tiled(monkeypatch):
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=6)
    sessions = _make_sessions(6)

    agent_admin_window.build_monitor_layout(project, sessions)

    layout_calls = [c for c in fake.calls if c and c[0] == "select-layout"]
    assert len(layout_calls) == 1, f"expected one select-layout call, got {layout_calls}"
    assert layout_calls[0][-1] == "tiled", (
        f"6-engineer monitor should use tiled layout, got {layout_calls[0]}"
    )


def test_build_monitor_layout_seven_panes_includes_all(monkeypatch):
    """Capacity > 4: ensure no engineer is silently dropped."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=7)
    sessions = _make_sessions(7)

    agent_admin_window.build_monitor_layout(project, sessions)

    targets = _attach_targets(fake.calls)
    expected = [f"demo-seat{i}" for i in range(7)]
    assert sorted(set(targets)) == sorted(expected), (
        f"all 7 engineer sessions must be attached; got {targets}"
    )


def test_build_monitor_layout_four_panes_unchanged(monkeypatch):
    """Backwards compat: 4 engineers still produce exactly 3 splits + tiled."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=4)
    sessions = _make_sessions(4)

    agent_admin_window.build_monitor_layout(project, sessions)

    assert _split_count(fake.calls) == 3
    layout_calls = [c for c in fake.calls if c and c[0] == "select-layout"]
    assert len(layout_calls) == 1 and layout_calls[0][-1] == "tiled"


def test_build_monitor_layout_two_panes_no_extras(monkeypatch):
    """2 engineers → 1 split, no extra splits from the new loop."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=2)
    sessions = _make_sessions(2)

    agent_admin_window.build_monitor_layout(project, sessions)
    assert _split_count(fake.calls) == 1


# ── Pane labeling: every pane gets the engineer_id as its title ───────

def _label_calls(calls: list[list[str]]) -> dict[str, str]:
    """Extract pane_id → title mapping from `select-pane -t X -T Y` calls."""
    out: dict[str, str] = {}
    for c in calls:
        if len(c) >= 5 and c[0] == "select-pane" and "-T" in c:
            target = c[c.index("-t") + 1] if "-t" in c else None
            title = c[c.index("-T") + 1]
            if target:
                out[target] = title
    return out


def test_pane_labels_set_for_all_engineers(monkeypatch):
    """Every visible engineer must have a `select-pane -T <engineer_id>` call."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=6)
    sessions = _make_sessions(6)

    agent_admin_window.build_monitor_layout(project, sessions)

    labels = _label_calls(fake.calls)
    titled = sorted(labels.values())
    expected = sorted(f"seat{i}" for i in range(6))
    assert titled == expected, (
        f"every engineer must be labeled exactly once; got titles={titled}"
    )


def test_pane_border_status_enabled(monkeypatch):
    """pane-border-status must be set to 'top' so labels are visible."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=3)
    sessions = _make_sessions(3)

    agent_admin_window.build_monitor_layout(project, sessions)

    border_calls = [
        c for c in fake.calls
        if c[:2] == ["set-option", "-t"] and "pane-border-status" in c
    ]
    assert border_calls, "pane-border-status must be configured"
    assert "top" in border_calls[0], (
        f"pane-border-status should be 'top', got {border_calls[0]}"
    )


def test_window_renamed_to_project_name(monkeypatch):
    """rename-window must use project.name (not the default 'tmux')."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=3)
    sessions = _make_sessions(3)

    agent_admin_window.build_monitor_layout(project, sessions)

    rename_calls = [c for c in fake.calls if c and c[0] == "rename-window"]
    assert rename_calls, "monitor window should be renamed from 'tmux'"
    assert rename_calls[0][-1] == project.name, (
        f"window should be renamed to {project.name!r}, got {rename_calls[0]}"
    )


def test_seat_user_option_set_for_each_pane(monkeypatch):
    """Each pane must have @seat set — labels survive inner-session OSC rewrites."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=6)
    sessions = _make_sessions(6)

    agent_admin_window.build_monitor_layout(project, sessions)

    at_seat_calls = [
        c for c in fake.calls
        if c[:2] == ["set-option", "-p"] and "@seat" in c
    ]
    assert len(at_seat_calls) == 6, (
        f"all 6 panes must have @seat set; got {len(at_seat_calls)} calls"
    )
    seats_set = sorted(c[-1] for c in at_seat_calls)
    assert seats_set == sorted(f"seat{i}" for i in range(6))


def test_pane_border_format_references_seat_option(monkeypatch):
    """pane-border-format must use @seat so inner pane_title cannot override."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=3)
    sessions = _make_sessions(3)

    agent_admin_window.build_monitor_layout(project, sessions)

    fmt_calls = [c for c in fake.calls if "pane-border-format" in c]
    assert fmt_calls, "pane-border-format must be configured"
    fmt = fmt_calls[0][-1]
    assert "@seat" in fmt, (
        f"pane-border-format must reference @seat (not just pane_title), got {fmt!r}"
    )


def test_automatic_rename_disabled(monkeypatch):
    """automatic-rename off — otherwise window name reverts to pane_current_command."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=3)
    sessions = _make_sessions(3)

    agent_admin_window.build_monitor_layout(project, sessions)

    rename_off = [
        c for c in fake.calls
        if "automatic-rename" in c and "off" in c
    ]
    assert rename_off, (
        "automatic-rename must be disabled or the renamed window will revert"
    )


# ── Nested-tmux ergonomics: outer prefix + mouse off ─────────────────

def test_monitor_prefix_remapped_to_ctrl_a(monkeypatch):
    """Outer monitor prefix must be C-a — Ctrl+B is reserved for inner sessions."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=3)
    sessions = _make_sessions(3)

    agent_admin_window.build_monitor_layout(project, sessions)

    prefix_calls = [
        c for c in fake.calls
        if c[:2] == ["set-option", "-t"] and "prefix" in c and "C-a" in c
    ]
    assert prefix_calls, (
        "monitor session must rebind prefix to C-a so Ctrl+B reaches inner sessions"
    )


def test_frontstage_engineer_skipped(monkeypatch):
    """koder / frontstage are OpenClaw agents — must NOT get a monitor pane.

    Without this guard, opening the monitor would auto-spawn an
    `<project>-koder-claude` tmux session that displaces the real koder
    identity managed by OpenClaw.
    """
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    # 5 normal seats + koder mixed in → koder must be filtered out.
    project = SimpleNamespace(
        name="demo",
        repo_root="/tmp/demo-repo",
        monitor_session="project-demo-monitor",
        monitor_engineers=["seat0", "koder", "seat1", "seat2", "seat3", "frontstage", "seat4"],
        engineers=["seat0", "koder", "seat1", "seat2", "seat3", "frontstage", "seat4"],
        monitor_max_panes=6,
        window_mode="project-monitor",
    )
    sessions = {f"seat{i}": SimpleNamespace(
        engineer_id=f"seat{i}",
        session=f"demo-seat{i}",
        workspace=f"/tmp/ws{i}",
    ) for i in range(5)}
    sessions["koder"] = SimpleNamespace(engineer_id="koder", session="demo-koder", workspace="/tmp/wsk")
    sessions["frontstage"] = SimpleNamespace(engineer_id="frontstage", session="demo-frontstage", workspace="/tmp/wsf")

    # All sessions exist, so without filtering koder/frontstage WOULD be picked.
    monkeypatch.setattr(agent_admin_window, "tmux_has_session", lambda s: True)
    monkeypatch.setattr(agent_admin_window, "tmux_with_retry", fake)
    monkeypatch.setattr(agent_admin_window, "tmux_window_panes", lambda _: list(fake.panes))

    agent_admin_window.build_monitor_layout(project, sessions)

    targets = _attach_targets(fake.calls)
    assert "demo-koder" not in targets, (
        f"koder must NOT be attached as a tmux seat; got {targets}"
    )
    assert "demo-frontstage" not in targets, (
        f"frontstage alias must also be filtered; got {targets}"
    )
    # All 5 normal seats should be there
    for i in range(5):
        assert f"demo-seat{i}" in targets, f"seat{i} missing from monitor; got {targets}"


def test_monitor_mouse_disabled(monkeypatch):
    """Mouse must be off on monitor — clicks belong to inner sessions."""
    fake = _FakeTmux()
    _install_fakes(monkeypatch, fake)
    project = _make_project(n=3)
    sessions = _make_sessions(3)

    agent_admin_window.build_monitor_layout(project, sessions)

    mouse_off = [
        c for c in fake.calls
        if c[:2] == ["set-option", "-t"] and "mouse" in c and "off" in c
    ]
    assert mouse_off, (
        "monitor session must disable mouse so inner sessions handle clicks"
    )
