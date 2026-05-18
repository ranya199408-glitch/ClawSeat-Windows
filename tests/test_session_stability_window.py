"""Audit finding #5 — _assert_session_running stability window.

Some agent CLIs (notably codex) can spawn-then-exit within a few seconds
of tmux new-session. The immediate post-launch pane check passes, but
the pane vanishes seconds later — operator finds an empty grid with no
error reported. The stability window (SESSION_STABILITY_WINDOW_SECONDS)
re-verifies after a short pause to surface these flaky launches as
SessionStartError instead of silently swallowing.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_agent_admin_session_isolation_helpers", _HELPERS_PATH
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

aas = _HELPERS.aas
_make_service = _HELPERS._make_service
_make_session = _HELPERS._make_session


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def test_assert_session_running_raises_when_session_dies_in_stability_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Pane present at immediate check, gone after stability window → fail-closed."""
    # Speed test up — tiny window
    monkeypatch.setattr(aas, "SESSION_STABILITY_WINDOW_SECONDS", 0.05)

    session = _make_session(
        tmp_path,
        engineer_id="builder-image",
        tool="codex",
        auth_mode="oauth",
        provider="openai",
    )
    svc, hooks = _make_service(tmp_path, session)

    # First tmux_has_session call returns True (immediate check passes),
    # second call (after stability window sleep) returns False (session died).
    has_session_calls = [True, False]
    hooks.tmux_has_session.side_effect = lambda *_a, **_k: has_session_calls.pop(0)

    # _is_session_onboarding returns False (no markers); list-panes returns a pane
    monkeypatch.setattr(svc, "_is_session_onboarding", lambda *_a, **_k: False)
    monkeypatch.setattr(svc, "_run_tmux_with_retry",
                        lambda *_a, **_k: _completed("%0|codex"))
    monkeypatch.setattr(svc, "_session_window_state", lambda *_a, **_k: "(test stub)")

    with pytest.raises(aas.SessionStartError) as ei:
        svc._assert_session_running(session, operation="test op")
    assert "stability window" in str(ei.value)
    assert "spawn-then-exit" in str(ei.value)


def test_assert_session_running_raises_when_panes_vanish_in_stability_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Session exists at both checks, but list-panes goes empty after window → fail."""
    monkeypatch.setattr(aas, "SESSION_STABILITY_WINDOW_SECONDS", 0.05)

    session = _make_session(
        tmp_path,
        engineer_id="builder-image",
        tool="codex",
        auth_mode="oauth",
        provider="openai",
    )
    svc, hooks = _make_service(tmp_path, session)
    hooks.tmux_has_session.return_value = True
    monkeypatch.setattr(svc, "_is_session_onboarding", lambda *_a, **_k: False)

    # First list-panes returns a pane (passes immediate check), second returns empty
    pane_outputs = [_completed("%0|codex"), _completed("")]
    monkeypatch.setattr(svc, "_run_tmux_with_retry",
                        lambda *_a, **_k: pane_outputs.pop(0))
    monkeypatch.setattr(svc, "_session_window_state", lambda *_a, **_k: "(test stub)")

    with pytest.raises(aas.SessionStartError) as ei:
        svc._assert_session_running(session, operation="test op")
    assert "panes vanished" in str(ei.value)


def test_assert_session_running_passes_when_session_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Stable session passes both checks → no exception."""
    monkeypatch.setattr(aas, "SESSION_STABILITY_WINDOW_SECONDS", 0.05)

    session = _make_session(
        tmp_path,
        engineer_id="memory",
        tool="claude",
        auth_mode="api",
        provider="minimax",
    )
    svc, hooks = _make_service(tmp_path, session)
    hooks.tmux_has_session.return_value = True
    monkeypatch.setattr(svc, "_is_session_onboarding", lambda *_a, **_k: False)
    monkeypatch.setattr(svc, "_run_tmux_with_retry",
                        lambda *_a, **_k: _completed("%0|claude"))
    monkeypatch.setattr(svc, "_session_window_state", lambda *_a, **_k: "(test stub)")

    svc._assert_session_running(session, operation="test op")  # no exception


def test_assert_session_running_skips_window_when_onboarding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """ONBOARDING_DETECTED short-circuits before the stability window
    (operator interaction is expected to take >> window length)."""
    monkeypatch.setattr(aas, "SESSION_STABILITY_WINDOW_SECONDS", 5.0)  # would be slow if reached

    session = _make_session(
        tmp_path,
        engineer_id="memory",
        tool="claude",
        auth_mode="oauth",
        provider="anthropic",
    )
    svc, hooks = _make_service(tmp_path, session)
    hooks.tmux_has_session.return_value = True
    monkeypatch.setattr(svc, "_is_session_onboarding", lambda *_a, **_k: True)

    import time as _t
    t0 = _t.monotonic()
    svc._assert_session_running(session, operation="test op")
    assert _t.monotonic() - t0 < 2.0  # didn't sleep through the 5s window
