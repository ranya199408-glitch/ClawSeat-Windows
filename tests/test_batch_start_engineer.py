"""Unit tests for `agent-admin session batch-start-engineer`.

The command exists to replace a brittle shell idiom:

    for seat in A B C; do session start-engineer $seat &; done
    wait
    window open-monitor <project>

Operators keep forgetting the `wait`, causing Phase 2 (iTerm window open)
to fire while Phase 1 tmux sessions are still initialising — the
`tmux_has_session` filter inside `open_project_tabs_window` silently
drops the not-yet-ready seats and leaves partial tabs.

These tests lock the CRITICAL invariants:
  1. Every requested engineer actually has its start_engineer called.
  2. All Phase 1 start_engineer calls complete before the Phase 2
     open_monitor_window call fires. (No race.)
  3. If any Phase 1 seat fails, Phase 2 is skipped.
  4. --no-iterm skips Phase 2 even on full success.
  5. Duplicate engineer ids in the command line don't cause double-start.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))

from agent_admin_commands import CommandHandlers, CommandHooks  # noqa: E402


class _FakeSessionService:
    def __init__(self) -> None:
        self.started: list[tuple[str, float]] = []
        self.start_lock = threading.Lock()
        # Whitelist of engineer ids that should "fail" to start.
        self.fail_ids: set[str] = set()

    def start_engineer(self, session, reset: bool = False) -> None:  # noqa: ARG002
        # Simulate real work so the thread pool can interleave.
        time.sleep(0.01)
        if session.engineer_id in self.fail_ids:
            raise RuntimeError(f"simulated start failure for {session.engineer_id}")
        with self.start_lock:
            self.started.append((session.engineer_id, time.monotonic()))

    def start_project(self, project, ensure_monitor: bool = True, reset: bool = False):  # noqa: ARG002, D401
        pass


class _Recorder:
    """Records the time (monotonic) when it fires.

    Used to verify open_monitor_window fires only AFTER every start_engineer
    has returned — the whole point of batch-start-engineer is that Phase 2
    cannot begin while Phase 1 work is still in flight.
    """

    def __init__(self) -> None:
        self.fired_at: float | None = None
        self.fired_with_sessions: dict | None = None

    def __call__(self, project, sessions, engineers):  # noqa: ARG002
        self.fired_at = time.monotonic()
        self.fired_with_sessions = sessions


@pytest.fixture(autouse=True)
def _caller_dispatch_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "caller.toml"
    profile.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "planner"',
                'display_name = "planner"',
                'role = "planner"',
                "dispatch_authority = true",
                "escalation_authority = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")


def _make_handlers(
    *,
    engineer_ids: list[str],
    project_name: str = "demo",
    monitor_engineers: list[str] | None = None,
    window_mode: str = "tabs-1up",
    fail_ids: set[str] | None = None,
    tool_by_engineer: dict[str, str] | None = None,
    auth_by_engineer: dict[str, str] | None = None,
    provider_by_engineer: dict[str, str] | None = None,
    seat_overrides: dict[str, dict[str, str]] | None = None,
    provision_heartbeat=None,
):
    svc = _FakeSessionService()
    if fail_ids:
        svc.fail_ids = fail_ids
    open_recorder = _Recorder()

    def resolve(eid: str, project_name: str | None = None):  # noqa: ARG001
        tool = (tool_by_engineer or {}).get(eid, "claude")
        auth_mode = (auth_by_engineer or {}).get(eid, "oauth")
        provider = (provider_by_engineer or {}).get(
            eid,
            {"claude": "anthropic", "codex": "openai", "gemini": "google"}.get(tool, "unknown"),
        )
        return SimpleNamespace(
            engineer_id=eid,
            session=f"{project_name or 'demo'}-{eid}-{tool}",
            project=project_name or "demo",
            tool=tool,
            auth_mode=auth_mode,
            provider=provider,
        )

    def default_provision_heartbeat(session):  # noqa: ARG001
        return (True, "")

    def load_project_or_current(project_name: str | None):
        return SimpleNamespace(
            name=project_name or "demo",
            monitor_engineers=monitor_engineers if monitor_engineers is not None else engineer_ids,
            engineers=engineer_ids,
            window_mode=window_mode,
            seat_overrides=seat_overrides or {},
        )

    def load_project_sessions(project_name: str):  # noqa: ARG001
        return {eid: resolve(eid, project_name) for eid in engineer_ids}

    def load_engineers():
        return {}

    hooks = CommandHooks(
        error_cls=RuntimeError,
        load_project_or_current=load_project_or_current,
        resolve_engineer_session=resolve,
        provision_session_heartbeat=provision_heartbeat or default_provision_heartbeat,
        load_project_sessions=load_project_sessions,
        tmux_has_session=lambda _name: True,
        load_projects=lambda: {},
        get_current_project_name=lambda _projects: None,
        session_service=svc,
        open_monitor_window=open_recorder,
        open_dashboard_window=lambda _projects: None,
        open_project_tabs_window=lambda _p, _s, _e: None,
        open_engineer_window=lambda _s, _e: None,
        load_engineers=load_engineers,
    )
    return CommandHandlers(hooks), svc, open_recorder


def _args(engineers, **overrides):
    defaults = dict(project=None, reset=False, no_iterm=False, accept_override=False)
    defaults.update(overrides)
    return SimpleNamespace(engineers=engineers, **defaults)


def _start_args(engineer: str, **overrides):
    defaults = dict(project=None, reset=False, accept_override=False)
    defaults.update(overrides)
    return SimpleNamespace(engineer=engineer, **defaults)


def _heartbeat_args(engineer: str, **overrides):
    defaults = dict(project=None, force=False, dry_run=False)
    defaults.update(overrides)
    return SimpleNamespace(engineer=engineer, **defaults)


# ── Invariant 1: every requested seat is started ──────────────────────────────


def test_all_requested_seats_are_started():
    handlers, svc, _open = _make_handlers(
        engineer_ids=["planner", "builder-1", "reviewer-1", "designer-1"],
    )
    handlers.session_batch_start_engineer(
        _args(["planner", "builder-1", "reviewer-1", "designer-1"])
    )
    started_ids = [eid for eid, _ in svc.started]
    assert sorted(started_ids) == ["builder-1", "designer-1", "planner", "reviewer-1"]


def test_start_engineer_skips_heartbeat_for_codex_memory(capsys):
    calls: list[str] = []

    def provision_heartbeat(session):
        calls.append(session.engineer_id)
        return (True, "heartbeat should not run for codex")

    handlers, svc, _open = _make_handlers(
        engineer_ids=["memory"],
        tool_by_engineer={"memory": "codex"},
        provision_heartbeat=provision_heartbeat,
    )

    rc = handlers.session_start_engineer(_start_args("memory", project="cartooner"))

    assert rc == 0
    assert [eid for eid, _ in svc.started] == ["memory"]
    assert calls == []
    out = capsys.readouterr().out
    assert "cartooner-memory-codex" in out
    assert "heartbeat" not in out


def test_batch_start_engineer_provisions_heartbeat_only_for_claude(capsys):
    calls: list[str] = []

    def provision_heartbeat(session):
        calls.append(session.engineer_id)
        return (True, f"{session.engineer_id}: heartbeat ok")

    engineer_ids = ["memory", "planner", "designer"]
    handlers, svc, _open = _make_handlers(
        engineer_ids=engineer_ids,
        tool_by_engineer={"memory": "codex", "planner": "claude", "designer": "gemini"},
        provision_heartbeat=provision_heartbeat,
    )

    rc = handlers.session_batch_start_engineer(_args(engineer_ids, project="cartooner"))

    assert rc == 0
    assert {eid for eid, _ in svc.started} == set(engineer_ids)
    assert calls == ["planner"]
    out = capsys.readouterr().out
    assert "planner: heartbeat ok" in out
    assert "memory: heartbeat" not in out
    assert "designer: heartbeat" not in out


def test_provision_heartbeat_gracefully_skips_codex_memory(capsys):
    def provision_heartbeat(session):  # noqa: ARG001
        raise AssertionError("non-Claude heartbeat skip should not call provision hook")

    handlers, _svc, _open = _make_handlers(
        engineer_ids=["memory"],
        tool_by_engineer={"memory": "codex"},
        provision_heartbeat=provision_heartbeat,
    )

    rc = handlers.session_provision_heartbeat(_heartbeat_args("memory", project="cartooner"))

    assert rc == 0
    out = capsys.readouterr().out
    assert "memory: heartbeat skipped for codex session" in out


def test_start_engineer_fails_when_project_seat_override_tool_mismatches():
    handlers, svc, _open = _make_handlers(
        engineer_ids=["memory"],
        tool_by_engineer={"memory": "codex"},
        seat_overrides={
            "memory": {
                "tool": "claude",
                "auth_mode": "oauth",
                "provider": "anthropic",
            }
        },
    )

    try:
        handlers.session_start_engineer(_start_args("memory", project="cartooner"))
    except RuntimeError as exc:
        message = str(exc)
        assert "project.toml seat_override requires tool=claude but got tool=codex" in message
        assert "Use --accept-override to bypass" in message
    else:
        raise AssertionError("expected project.toml seat_override mismatch to fail")

    assert svc.started == []


def test_start_engineer_accept_override_bypasses_mismatch(capsys):
    handlers, svc, _open = _make_handlers(
        engineer_ids=["memory"],
        tool_by_engineer={"memory": "codex"},
        seat_overrides={
            "memory": {
                "tool": "claude",
                "auth_mode": "oauth",
                "provider": "anthropic",
            }
        },
    )

    rc = handlers.session_start_engineer(
        _start_args("memory", project="cartooner", accept_override=True)
    )

    assert rc == 0
    assert [eid for eid, _ in svc.started] == ["memory"]
    assert "warn: project.toml seat_override requires tool=claude but got tool=codex" in capsys.readouterr().err


def test_start_engineer_project_seat_override_match_passes():
    handlers, svc, _open = _make_handlers(
        engineer_ids=["memory"],
        tool_by_engineer={"memory": "codex"},
        seat_overrides={
            "memory": {
                "tool": "codex",
                "auth_mode": "oauth",
                "provider": "openai",
            }
        },
    )

    rc = handlers.session_start_engineer(_start_args("memory", project="cartooner"))

    assert rc == 0
    assert [eid for eid, _ in svc.started] == ["memory"]


def test_batch_start_engineer_validates_overrides_before_any_spawn():
    handlers, svc, _open = _make_handlers(
        engineer_ids=["memory", "planner"],
        tool_by_engineer={"memory": "codex", "planner": "claude"},
        seat_overrides={
            "planner": {
                "tool": "codex",
                "auth_mode": "oauth",
                "provider": "openai",
            }
        },
    )

    try:
        handlers.session_batch_start_engineer(
            _args(["memory", "planner"], project="cartooner", no_iterm=True)
        )
    except RuntimeError as exc:
        assert "project.toml seat_override requires tool=codex but got tool=claude" in str(exc)
    else:
        raise AssertionError("expected batch-start-engineer override mismatch to fail")

    assert svc.started == []


# ── Invariant 2: Phase 2 fires AFTER all Phase 1 work finishes ───────────────


def test_phase2_fires_after_all_phase1_returns():
    engineer_ids = ["planner", "builder-1", "reviewer-1", "designer-1", "patrol-1"]
    handlers, svc, open_recorder = _make_handlers(engineer_ids=engineer_ids)
    handlers.session_batch_start_engineer(_args(engineer_ids))

    assert open_recorder.fired_at is not None, "open_monitor_window must fire"
    last_start_time = max(t for _eid, t in svc.started)
    # Phase 2 must start strictly after the slowest Phase 1 finishes.
    # (Monotonic clock — equal times would be legal in theory, but the
    # FakeSessionService sleeps 10ms which makes floating equality
    # vanishingly unlikely.)
    assert open_recorder.fired_at >= last_start_time, (
        "open_monitor_window fired before last start_engineer returned — "
        "this is the exact race the shell `wait` was there to prevent"
    )


# ── Invariant 3: failures skip Phase 2 ───────────────────────────────────────


def test_phase2_skipped_when_any_seat_fails():
    engineer_ids = ["planner", "builder-1", "reviewer-1"]
    handlers, _svc, open_recorder = _make_handlers(
        engineer_ids=engineer_ids,
        fail_ids={"builder-1"},
    )
    try:
        handlers.session_batch_start_engineer(_args(engineer_ids))
    except RuntimeError as exc:
        assert "builder-1" in str(exc)
        assert "1/3" in str(exc) or "failed" in str(exc).lower()
    else:
        raise AssertionError("expected RuntimeError when a seat fails to start")
    # Crucially, open_monitor_window must NOT have fired — we don't want
    # to present the operator with a half-populated iTerm window that
    # pretends the project is up.
    assert open_recorder.fired_at is None, (
        "open_monitor_window fired despite a Phase 1 failure — the operator "
        "would see an iTerm window missing the failed seat's tab and think "
        "everything succeeded"
    )


# ── Invariant 4: --no-iterm skips Phase 2 even on success ───────────────────


def test_no_iterm_flag_skips_phase2():
    engineer_ids = ["planner", "builder-1"]
    handlers, svc, open_recorder = _make_handlers(engineer_ids=engineer_ids)
    handlers.session_batch_start_engineer(_args(engineer_ids, no_iterm=True))

    # Phase 1 ran
    assert {eid for eid, _ in svc.started} == {"planner", "builder-1"}
    # Phase 2 did NOT run
    assert open_recorder.fired_at is None


# ── Invariant 5: duplicate ids don't cause double-start ───────────────────────


def test_duplicate_ids_deduped():
    # Operator typos `planner` twice — we should only start it once.
    handlers, svc, _open = _make_handlers(engineer_ids=["planner", "builder-1"])
    handlers.session_batch_start_engineer(
        _args(["planner", "builder-1", "planner"])
    )
    started_ids = [eid for eid, _ in svc.started]
    # planner should appear exactly once
    assert started_ids.count("planner") == 1
    assert started_ids.count("builder-1") == 1


# ── Invariant 6: empty engineer list is a hard error ──────────────────────────


def test_empty_engineer_list_raises():
    handlers, _svc, _open = _make_handlers(engineer_ids=[])
    try:
        handlers.session_batch_start_engineer(_args([]))
    except RuntimeError as exc:
        assert "requires" in str(exc) or "engineer" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for empty engineer list")


# ── Invariant 7: project with no monitor_engineers still completes Phase 1 ──


def test_empty_monitor_engineers_still_starts_phase1():
    engineer_ids = ["planner", "builder-1"]
    handlers, svc, open_recorder = _make_handlers(
        engineer_ids=engineer_ids,
        monitor_engineers=[],  # project has no monitor_engineers — Phase 2 no-op
    )
    handlers.session_batch_start_engineer(_args(engineer_ids))
    # Phase 1 still ran so the tmux sessions are up
    assert {eid for eid, _ in svc.started} == {"planner", "builder-1"}
    # Phase 2 explicitly skipped (no-op path), not failed
    assert open_recorder.fired_at is None
