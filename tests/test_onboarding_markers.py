"""Lock the CLAUDE_ONBOARDING_MARKERS table against real CLI pane samples.

Provenance of each sample below:
- claude 2.1.112  — package bundle strings + live-captured pane on OAuth setup
- codex  0.121.0  — package bundle strings + live first-run in isolated HOME
- gemini 0.38.1   — package bundle strings + live first-run in isolated HOME

If you upgrade a CLI and its TUI text drifts, UPDATE THE SAMPLE in this test
AND the marker row in _common.py at the same time. Do not silently relax an
assertion here — it is the only thing catching the drift before prod.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

from _common import CLAUDE_ONBOARDING_MARKERS, detect_claude_onboarding_step  # noqa: E402


# ── Table-level invariants ──────────────────────────────────────────────────


def test_no_duplicate_marker_strings():
    """Two rows with the same marker substring is a drift bug — the later row
    is dead code because detect_claude_onboarding_step returns on first match.
    """
    markers = [m for m, _step in CLAUDE_ONBOARDING_MARKERS]
    assert len(markers) == len(set(markers)), (
        "duplicate marker strings: "
        f"{[m for m in markers if markers.count(m) > 1]}"
    )


def test_step_name_cli_prefix():
    """Every step name must carry a CLI prefix (claude_/codex_/gemini_) so
    start_seat.py can surface 'which CLI is waiting' to the operator.
    """
    allowed_prefixes = ("claude_", "codex_", "gemini_")
    for marker, step in CLAUDE_ONBOARDING_MARKERS:
        assert step.startswith(allowed_prefixes), (
            f"step {step!r} for marker {marker!r} missing CLI prefix"
        )


def test_required_step_coverage():
    """Each CLI must cover at minimum: oauth_login entry + workspace_trust.
    Without these start_seat cannot distinguish 'waiting on login' from 'dead'.
    """
    step_set = {step for _marker, step in CLAUDE_ONBOARDING_MARKERS}
    required = {
        "claude_oauth_login",
        "claude_workspace_trust",
        "codex_oauth_login",
        "codex_workspace_trust",
        "gemini_oauth_login",
        "gemini_workspace_trust",
    }
    missing = required - step_set
    assert not missing, f"missing required step names: {sorted(missing)}"


# ── Real-sample detection ──────────────────────────────────────────────────


def test_detects_claude_oauth_login():
    pane = (
        "Claude needs to sign in.\n"
        "Browser didn't open? Use the url below to sign in:\n"
        "  https://claude.ai/oauth/authorize?..."
    )
    assert detect_claude_onboarding_step(pane) == "claude_oauth_login"


def test_detects_claude_oauth_code():
    pane = "Paste code here if prompted >"
    assert detect_claude_onboarding_step(pane) == "claude_oauth_code"


def test_detects_claude_workspace_trust():
    pane = (
        "Accessing workspace: /tmp/fake-home/project\n"
        "Do you want to trust this workspace? (y/n)"
    )
    assert detect_claude_onboarding_step(pane) == "claude_workspace_trust"


def test_detects_codex_oauth_login_menu():
    pane = (
        "How would you like to sign in?\n"
        "> Sign in with ChatGPT\n"
        "  Provide your own API key"
    )
    assert detect_claude_onboarding_step(pane) == "codex_oauth_login"


def test_detects_codex_api_key_menu():
    pane = (
        "How would you like to sign in?\n"
        "  Sign in with ChatGPT\n"
        "> Provide your own API key"
    )
    # Note: "Sign in with ChatGPT" fires first because it appears earlier in
    # the pane text. This is intentional — if the user is still on the menu,
    # either step is fine; start_seat just needs to know "waiting on human".
    step = detect_claude_onboarding_step(pane)
    assert step in {"codex_oauth_login", "codex_api_login"}


def test_detects_codex_oauth_code_prompt():
    pane = (
        "Finish signing in via your browser to continue.\n"
        "Enter this one-time code: ABCD-1234"
    )
    # Either oauth_login (browser hint) or oauth_code (device code) match —
    # both are valid "waiting on user" states for the same flow.
    assert detect_claude_onboarding_step(pane) in {"codex_oauth_login", "codex_oauth_code"}


def test_detects_codex_workspace_trust():
    pane = (
        "Do you trust the contents of this directory?\n"
        "  /tmp/fake-home/project"
    )
    assert detect_claude_onboarding_step(pane) == "codex_workspace_trust"


def test_detects_codex_approval_requested():
    pane = "Approval requested: run `rm -rf build/`"
    assert detect_claude_onboarding_step(pane) == "codex_approval_prompt"


def test_detects_codex_approval_needed():
    pane = "Approval needed in /tmp/fake-home/project before proceeding"
    assert detect_claude_onboarding_step(pane) == "codex_approval_prompt"


def test_detects_gemini_oauth_menu():
    pane = (
        "Select an auth method:\n"
        "> Sign in with Google\n"
        "  Use an API key"
    )
    assert detect_claude_onboarding_step(pane) == "gemini_oauth_menu"


def test_detects_gemini_oauth_login_wait():
    pane = "Waiting for authentication in your browser..."
    assert detect_claude_onboarding_step(pane) == "gemini_oauth_login"


def test_detects_gemini_workspace_trust():
    pane = (
        "Do you trust the files in this folder?\n"
        "  /tmp/fake-home/project"
    )
    assert detect_claude_onboarding_step(pane) == "gemini_workspace_trust"


# ── Negative cases — must not match on normal runtime text ─────────────────


def test_does_not_match_idle_prompt():
    pane = (
        "╭─── Claude Code v2.1.112 ────╮\n"
        "│            Welcome back!    │\n"
        "╰─────────────────────────────╯\n"
        "❯ "
    )
    assert detect_claude_onboarding_step(pane) is None


def test_does_not_match_plain_output():
    pane = "Hello world. This is just normal shell output with no onboarding cues."
    assert detect_claude_onboarding_step(pane) is None


def test_does_not_match_unrelated_url_mention():
    pane = "Check https://example.com/oauth for more info — this is docs, not a prompt"
    assert detect_claude_onboarding_step(pane) is None


# ── Sync invariant against heartbeat.py ────────────────────────────────────


def test_heartbeat_claude_markers_subset_of_common():
    """agent_admin_heartbeat.CLAUDE_ONBOARDING_MARKERS is Claude-only by design;
    every claude marker STRING it uses must also appear in _common.py so that
    start_seat and heartbeat agree on what 'Claude is still onboarding' looks
    like. (Step names are allowed to differ because heartbeat uses shorter
    local names; the substring is the thing that must not drift.)
    """
    sys.path.insert(0, str(_REPO / "core" / "scripts"))
    from agent_admin_heartbeat import (  # noqa: E402
        CLAUDE_ONBOARDING_MARKERS as HB_MARKERS,
    )

    common_strings = {m for m, _ in CLAUDE_ONBOARDING_MARKERS}

    # Only check rows whose step name indicates a claude auth-flow marker —
    # heartbeat also tracks non-auth first-run states ("welcome", "theme_setup",
    # "text_style") that start_seat doesn't need to know about.
    auth_step_substrings = (
        "oauth_login",
        "oauth_code",
        "oauth_continue",
        "oauth_error",
        "workspace_trust",
        "bypass_permissions",
    )
    for hb_marker, hb_step in HB_MARKERS:
        if not any(s in hb_step for s in auth_step_substrings):
            continue
        # Either an exact match (canonical), or heartbeat's marker is a
        # substring of a _common entry (heartbeat kept a shorter fallback
        # for line-wrapped panes — that's fine as long as the canonical
        # longer form still lives in _common.py).
        if hb_marker in common_strings:
            continue
        substring_of = [c for c in common_strings if hb_marker in c]
        assert substring_of, (
            f"heartbeat marker drift: {hb_marker!r} (step {hb_step!r}) "
            "not present in _common.py CLAUDE_ONBOARDING_MARKERS and not a "
            "substring of any canonical entry there"
        )
