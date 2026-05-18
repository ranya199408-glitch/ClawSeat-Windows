"""Lock the 'only planner can closeout to koder' guard in complete_handoff.py.

Background
----------
Historic follow-up #22:
  complete_handoff.py --target koder from a non-planner source silently
  falls into the tmux seat path. koder isn't a tmux session (it runs
  inside OpenClaw), so `notify` fails; but the Feishu
  OC_DELEGATION_REPORT_V1 routing is also skipped (that branch is gated
  on source=planner). The receipt hits disk but the user never sees it.

Live incident
-------------
In the followup-sendverify-race chain, qa-1 called
`complete_handoff.py --source qa-1 --target koder` and wrote a valid
DELIVERY.md + receipt. The receipt had zero feishu_delegation_report
fields — confirming the Feishu path was never triggered. The closeout
was effectively silent; koder only "knew" the chain was done because
a human was reading the receipt directory by hand.

Fix
---
`complete_handoff.py` now hard-rejects `target=heartbeat_owner` when
`source != active_loop_owner`. Specialists must close back to planner;
planner aggregates and forwards to koder via Feishu.

Why lock this
-------------
Without the guard, any future regression that drops the SystemExit
raise would silently route specialist closeouts through a dead tmux
path. Test exists precisely because the failure mode is INVISIBLE
(no user-facing error), so a human reviewer might not catch it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_COMPLETE_HANDOFF = _SCRIPTS / "complete_handoff.py"


# ── Helper: run complete_handoff.py and capture stderr ──────────────────


def _run_guard_probe(*, source: str, target: str, profile: Path) -> subprocess.CompletedProcess[str]:
    """Invoke complete_handoff.py with minimal valid args to hit the guard.

    We pass a non-existent task-id so the guard fires BEFORE disk I/O
    tries to write any delivery artifacts.  The only thing we care about
    in this test is whether the guard raises SystemExit with the right
    message.
    """
    return subprocess.run(
        [
            sys.executable,
            str(_COMPLETE_HANDOFF),
            "--profile", str(profile),
            "--source", source,
            "--target", target,
            "--task-id", "test-guard-probe",
            "--title", "guard probe",
            "--summary", "probe for koder-source guard",
        ],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def install_profile() -> Path:
    """The live install profile, known to have heartbeat_owner=koder
    and active_loop_owner=planner. Using the real profile avoids
    needing to spin up a synthetic one — the guard logic reads
    `profile.heartbeat_owner` and `profile.active_loop_owner`, which
    are exactly what we want to check against.
    """
    path = Path.home() / ".agents" / "profiles" / "install-profile-dynamic.toml"
    if not path.exists():
        pytest.skip(f"install profile not present: {path}")
    return path


# ── Guard behaviour ─────────────────────────────────────────────────────


def test_qa_to_koder_rejected(install_profile):
    """qa-1 → koder must be rejected. This is the exact violation that
    happened in followup-sendverify-race chain — qa-1 sent straight to
    koder, the Feishu path silently skipped, DELIVERY orphaned.
    """
    proc = _run_guard_probe(
        source="qa-1",
        target="koder",
        profile=install_profile,
    )
    assert proc.returncode != 0, (
        f"qa-1 → koder should be rejected, got rc={proc.returncode}"
    )
    err = proc.stderr.lower() + proc.stdout.lower()
    assert "planner" in err, (
        "guard message must name 'planner' as the required source"
    )
    assert "koder" in err or "heartbeat" in err, (
        "guard message must reference koder/heartbeat_owner"
    )


def test_reviewer_to_koder_rejected(install_profile):
    """Same guard for reviewer-1. Reviewer reports verdicts — those must
    go back to planner for aggregation, not short-circuit to koder.
    """
    proc = _run_guard_probe(
        source="reviewer-1",
        target="koder",
        profile=install_profile,
    )
    assert proc.returncode != 0, (
        f"reviewer-1 → koder should be rejected, got rc={proc.returncode}"
    )


def test_builder_to_koder_rejected(install_profile):
    """Builder must never closeout to koder directly. If koder ever
    dispatched straight to builder (bypassing planner, see followup #12),
    the guard here catches the closeout half of that protocol drift.
    """
    proc = _run_guard_probe(
        source="builder-1",
        target="koder",
        profile=install_profile,
    )
    assert proc.returncode != 0, (
        f"builder-1 → koder should be rejected, got rc={proc.returncode}"
    )


def test_designer_to_koder_rejected(install_profile):
    """Designer-1 same rule. Proves the guard is role-agnostic: it's
    not a whitelist, it's a strict 'only planner' rule.
    """
    proc = _run_guard_probe(
        source="designer-1",
        target="koder",
        profile=install_profile,
    )
    assert proc.returncode != 0, (
        f"designer-1 → koder should be rejected, got rc={proc.returncode}"
    )


def test_memory_to_koder_rejected(install_profile):
    """Memory seat is an exception-prone case (it's 'internal' and used
    out-of-band by installers). The guard still applies: memory closeout
    to koder is not a legitimate path. Memory answers queries to
    whoever called it, not to koder directly.
    """
    proc = _run_guard_probe(
        source="memory",
        target="koder",
        profile=install_profile,
    )
    assert proc.returncode != 0, (
        f"memory → koder should be rejected, got rc={proc.returncode}"
    )


def test_planner_to_koder_passes_guard(install_profile):
    """planner → koder must pass the guard. (It may fail later for other
    reasons — e.g. missing --frontstage-disposition or --user-summary,
    which are separately required for the frontstage path.)

    This test confirms the guard is a *filter*, not a general blocker —
    the legitimate path is still open.
    """
    proc = _run_guard_probe(
        source="planner",
        target="koder",
        profile=install_profile,
    )
    # The guard itself should NOT reject planner → koder. If the call
    # fails, it must be for a reason OTHER than the guard ("requires
    # source=planner").  We look at stderr for that specific phrase.
    guard_msg = "requires source='planner'"
    assert guard_msg not in proc.stderr, (
        f"planner → koder was rejected BY THE GUARD (unexpected); "
        f"stderr: {proc.stderr}"
    )
    # Other downstream rejections (disposition / user_summary / etc.)
    # are acceptable here — they're separate protocol rules, not this
    # test's concern.


# ── Message content lock ────────────────────────────────────────────────


def test_guard_message_references_followup_22_context(install_profile):
    """Lock the guard's error message shape. If someone rewrites this
    error to be less informative, the specialist agent might not
    understand WHY its closeout was rejected, and might retry with the
    same broken pattern.

    Rules the message must satisfy:
      - name the actual offending source (so agent knows it's about
        its own identity)
      - name the expected source ('planner')
      - mention 'koder' or 'heartbeat_owner' (the target term)
      - hint at the corrective action (close back to planner)
    """
    proc = _run_guard_probe(
        source="qa-1",
        target="koder",
        profile=install_profile,
    )
    msg = (proc.stderr + proc.stdout).lower()
    assert "qa-1" in msg, "must echo offending source"
    assert "planner" in msg, "must name required source"
    assert "koder" in msg or "heartbeat" in msg, (
        "must reference the target role"
    )
    # The corrective action phrase — 'close back' or 'aggregate' is
    # enough to signal 'go through planner'.
    assert any(hint in msg for hint in ("close back", "aggregate", "forward")), (
        "guard message should hint at corrective action"
    )
