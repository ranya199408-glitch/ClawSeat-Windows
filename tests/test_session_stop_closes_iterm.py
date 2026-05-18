"""Tests for T12 + RCA 2026-04-25: session stop-engineer closes iTerm pane (not tab) before tmux kill.

Covers:
  1. test_stop_engineer_closes_iterm_pane_when_tty_found
  2. test_stop_engineer_warns_when_iterm_pane_not_found
  3. test_stop_engineer_warns_on_iterm_close_error
  4. test_stop_engineer_default_does_not_close_iterm  — F1 regression canary
  5. test_stop_engineer_no_tty_skips_iterm_close
  6. test_session_stop_engineer_cli_passes_close_iterm_pane_true_by_default
  7. test_iterm_close_template_uses_close_s_not_close_t  — RCA 2026-04-25 pin
  8. test_stop_engineer_legacy_close_iterm_tab_kwarg_still_works  — backward compat
  9. test_close_pane_only_targets_one_session_in_multi_pane_tab  — multi-pane safety
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas
from agent_admin_commands import CommandHandlers


# ── helpers ───────────────────────────────────────────────────────────────────


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

def _make_session(name: str = "test-session") -> SimpleNamespace:
    return SimpleNamespace(session=name)


def _make_service() -> aas.SessionService:
    hooks = MagicMock()
    hooks.tmux_has_session.return_value = True
    return aas.SessionService(hooks)


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: close_iterm_pane=True + tty found → pane closed + tmux killed
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_engineer_closes_iterm_pane_when_tty_found(capsys):
    svc = _make_service()
    session = _make_session("koder-1")

    with (
        patch.object(aas, "_get_tmux_tty", return_value="/dev/ttys001") as mock_tty,
        patch.object(aas, "_close_iterm_pane_by_tty", return_value={"status": "ok", "detail": None}) as mock_close,
        patch.object(svc, "_run_tmux_with_retry") as mock_tmux,
    ):
        svc.stop_engineer(session, close_iterm_pane=True)

    mock_tty.assert_called_once_with("koder-1")
    mock_close.assert_called_once_with("/dev/ttys001")
    mock_tmux.assert_called_once()
    assert "iterm_pane_closed" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: close_iterm_pane=True + pane not found → warn stderr + tmux killed
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_engineer_warns_when_iterm_pane_not_found(capsys):
    svc = _make_service()
    session = _make_session("koder-2")

    with (
        patch.object(aas, "_get_tmux_tty", return_value="/dev/ttys002"),
        patch.object(aas, "_close_iterm_pane_by_tty", return_value={"status": "not_found", "detail": "no match"}),
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.stop_engineer(session, close_iterm_pane=True)

    err = capsys.readouterr().err
    assert "iterm_pane_not_found" in err


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: close_iterm_pane=True + osascript error → warn stderr + tmux killed
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_engineer_warns_on_iterm_close_error(capsys):
    svc = _make_service()
    session = _make_session("koder-3")

    with (
        patch.object(aas, "_get_tmux_tty", return_value="/dev/ttys003"),
        patch.object(aas, "_close_iterm_pane_by_tty", return_value={"status": "error", "detail": "timeout"}),
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.stop_engineer(session, close_iterm_pane=True)

    err = capsys.readouterr().err
    assert "iterm_pane_close_failed" in err
    assert "timeout" in err


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 (F1 regression canary): default stop_engineer() does NOT close iTerm
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_engineer_default_does_not_close_iterm():
    svc = _make_service()
    session = _make_session("koder-4")

    with (
        patch.object(aas, "_get_tmux_tty") as mock_tty,
        patch.object(aas, "_close_iterm_pane_by_tty") as mock_close,
        patch.object(svc, "_run_tmux_with_retry") as mock_tmux,
    ):
        svc.stop_engineer(session)  # default: close_iterm_pane=False

    mock_tty.assert_not_called()
    mock_close.assert_not_called()
    mock_tmux.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: close_iterm_pane=True + no tty → _close_iterm_pane_by_tty never called
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_engineer_no_tty_skips_iterm_close():
    svc = _make_service()
    session = _make_session("koder-5")

    with (
        patch.object(aas, "_get_tmux_tty", return_value=None),
        patch.object(aas, "_close_iterm_pane_by_tty") as mock_close,
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.stop_engineer(session, close_iterm_pane=True)

    mock_close.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Test 6: CLI handler passes close_iterm_pane=True by default
# ══════════════════════════════════════════════════════════════════════════════

def test_session_stop_engineer_cli_passes_close_iterm_pane_true_by_default():
    """session_stop_engineer with args.keep_iterm_tab=False → close_iterm_pane=True."""
    fake_session = _make_session("koder-6")
    mock_hooks = MagicMock()
    mock_hooks.resolve_engineer_session.return_value = fake_session

    handlers = CommandHandlers(mock_hooks)
    args = SimpleNamespace(engineer="koder", project=None, keep_iterm_tab=False)
    handlers.session_stop_engineer(args)

    mock_hooks.session_service.stop_engineer.assert_called_once_with(
        fake_session, close_iterm_pane=True
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 7 (RCA 2026-04-25 pin): AppleScript template uses `close s`, NOT `close t`
# Closing the entire tab nukes all sibling panes — the cartooner 6-pane RCA.
# ══════════════════════════════════════════════════════════════════════════════

def test_iterm_close_template_uses_close_s_not_close_t():
    template = aas._ITERM_CLOSE_SCRIPT_TEMPLATE
    assert "close s" in template, (
        "AppleScript must close the session/pane (close s), not the tab (close t). "
        "RCA 2026-04-25: closing the tab nukes sibling panes."
    )
    assert "\nclose t\n" not in template and " close t " not in template, (
        "`close t` must not appear — it would close the entire tab."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Test 8 (backward compat): legacy close_iterm_tab kwarg still accepted
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_engineer_legacy_close_iterm_tab_kwarg_still_works(capsys):
    """External callers still passing close_iterm_tab=True must work, mapping to pane close."""
    svc = _make_service()
    session = _make_session("koder-7")

    with (
        patch.object(aas, "_get_tmux_tty", return_value="/dev/ttys007"),
        patch.object(aas, "_close_iterm_pane_by_tty", return_value={"status": "ok", "detail": None}) as mock_close,
        patch.object(svc, "_run_tmux_with_retry"),
    ):
        svc.stop_engineer(session, close_iterm_tab=True)  # legacy kwarg name

    mock_close.assert_called_once_with("/dev/ttys007")


# ══════════════════════════════════════════════════════════════════════════════
# Test 9 (multi-pane safety): real simulation of 6-session tab
#
# Real fake-iTerm model + AppleScript template evaluator.  Closes the model
# according to the template's actual `close s` / `close t` keyword.
# Mutation-verified: replacing production `close s` → `close t` collapses
# all 6 sessions and the assertion correctly fails.
# ══════════════════════════════════════════════════════════════════════════════

import re


class FakeITermSession:
    """Fake iTerm2 session/pane.  alive=False after close()."""
    def __init__(self, tty: str) -> None:
        self.tty = tty
        self.alive = True


class FakeITermTab:
    """Fake iTerm2 tab containing N sessions.  Supports both `close s` and `close t` semantics."""
    def __init__(self, sessions: list[FakeITermSession]) -> None:
        self.sessions = sessions

    def find_session_by_tty(self, tty: str) -> FakeITermSession | None:
        for s in self.sessions:
            if s.tty == tty and s.alive:
                return s
        return None


def _evaluate_iterm_close_template(template: str, tty: str, tab: FakeITermTab) -> str:
    """Mini AppleScript-template evaluator.

    Detects the close-action keyword inside the matched-tty block of the
    production template:
      - `close s` → close the matching session only (sibling panes survive)
      - `close t` → close the entire tab (all sibling panes die — the RCA bug)

    Returns "ok" / "not_found" matching osascript output of the production helper.
    """
    rendered = template.replace("{tty}", tty)
    # Search for the action verb on its own line inside the inner repeat block.
    # The production template puts `close s` (or `close t`) on its own indented line.
    action_match = re.search(r"^\s+close\s+(s|t)\s*$", rendered, re.MULTILINE)
    if not action_match:
        raise ValueError(
            f"AppleScript template does not contain a `close s` or `close t` action; "
            f"template:\n{rendered}"
        )
    action = action_match.group(1)

    target = tab.find_session_by_tty(tty)
    if target is None:
        return "not_found"

    if action == "s":
        # Close only the matching session/pane.
        target.alive = False
    else:  # action == "t"
        # Close the entire tab — every session dies.
        for s in tab.sessions:
            s.alive = False
    return "ok"


def test_close_pane_preserves_5_siblings_real_simulation():
    """Real 6-session simulation: the production AppleScript template, evaluated
    against a fake iTerm model, must leave 5 siblings alive when only one pane
    is targeted.

    Mutation guarantee: if production switches `close s` → `close t`, the
    evaluator will close all 6 sessions and len(surviving) == 5 fails.
    """
    sessions = [FakeITermSession(f"/dev/ttys{i:03d}") for i in range(100, 106)]
    tab = FakeITermTab(sessions)
    target_tty = "/dev/ttys102"

    # Read production template as-is (no monkey-patch).
    template = aas._ITERM_CLOSE_SCRIPT_TEMPLATE

    result = _evaluate_iterm_close_template(template, target_tty, tab)
    assert result == "ok", f"evaluator should find target tty; got {result!r}"

    surviving = [s for s in tab.sessions if s.alive]
    closed = [s for s in tab.sessions if not s.alive]

    assert len(surviving) == 5, (
        f"Expected 5 sibling panes to survive after closing 1; got {len(surviving)}.\n"
        f"This means the template's close-action verb killed more than the targeted pane.\n"
        f"surviving ttys: {[s.tty for s in surviving]}"
    )
    assert len(closed) == 1, f"Expected exactly 1 closed pane; got {len(closed)}"
    assert closed[0].tty == target_tty, (
        f"The closed pane must be the targeted tty; got {closed[0].tty!r}"
    )


def test_close_pane_evaluator_correctly_models_close_t_bug():
    """Self-test of the evaluator: a template with `close t` MUST kill all siblings.

    This pins the evaluator's mutation-detection capability — without this, a
    template change from `close s` to `close t` could silently pass."""
    buggy_template = """\
tell application "iTerm"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if tty of s is "{tty}" then
                    close t
                    return "ok"
                end if
            end repeat
        end repeat
    end repeat
    return "not_found"
end tell"""
    sessions = [FakeITermSession(f"/dev/ttys{i:03d}") for i in range(100, 106)]
    tab = FakeITermTab(sessions)
    result = _evaluate_iterm_close_template(buggy_template, "/dev/ttys102", tab)
    assert result == "ok"
    surviving = [s for s in tab.sessions if s.alive]
    assert len(surviving) == 0, (
        f"`close t` must kill all 6 sessions in the tab; got {len(surviving)} surviving"
    )
