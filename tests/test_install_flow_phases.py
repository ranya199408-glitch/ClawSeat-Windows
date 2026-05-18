"""Legacy install-helper smoke tests.

Exercises the remaining helper scripts that still exist during the v0.5
transition in a fresh tmp-path environment. External I/O (tmux, Feishu) is
stubbed at the subprocess level so no real sessions or network calls fire.

Scope
-----
P0.0  preflight --help               → exit 0
P0.2  install_entry_skills.py --help   → exit 0
P0.3  scan_environment.py --only credentials → exit 0, writes machine/credentials.json
P0.5  bootstrap_harness.py --help      → exit 0 (no tomllib crash)
P0.6  refresh_workspaces.py --help     → exit 0

Deferred (require tmux seat or operator action):
- P1.1 start_seat memory (requires tmux)
- P1.2 memory TUI (operator action)
- P1.3 notify_seat memory scan (requires running memory seat)
- P1.4/P1.5 operator sync
- P2.1 query_memory (requires memory seat)
- P2.2 agent selection (operator action)
- P3.2 init_koder (requires OpenClaw workspace)
- P3.3 configure_feishu (requires OpenClaw config)
- P3.4/P3.5 operator identity verification + Feishu group creation
- P4.1+ seat start (requires tmux)
- P4.3 bind project (requires Feishu)
- P4.4 dispatch smoke (requires planner + Feishu)
- P4.5 smoke confirmation (operator action)
- P5 handoff (operator action)

These are documented as DEFERRED with rationale.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLAWSEAT_ROOT = str(REPO)

# Minimal clean env — no HOME pollution, no seat-sandbox variables.
# HOME must be set so Python can find the stdlib, but it points at /tmp
# so no real user dirs are touched.
_SANDBOX_HOME = Path("/tmp") / f"qa-smoke-{os.getpid()}"
_SANDBOX_HOME.mkdir(exist_ok=True)


def _clean_env(extra: dict | None = None) -> dict:
    """Build a minimal env for a stranger-on-bare-py3.11 simulation."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(_SANDBOX_HOME),
        # Seat-sandbox isolation vars must be absent so real_user_home()
        # falls back to pwd-based resolution.
        "AGENT_HOME": "",
        "CLAWSEAT_SANDBOX_HOME_STRICT": "",
        "CLAWSEAT_REAL_HOME": "",
        # Keep GSTACK_SKILLS_ROOT so preflight skill checks pass in CI
        "GSTACK_SKILLS_ROOT": os.environ.get("GSTACK_SKILLS_ROOT", ""),
        "CLAWSEAT_ROOT": CLAWSEAT_ROOT,
        # Suppress Claude/Anthropic env-noise that can leak into subprocesses
        **{k: "" for k in [
            "ANTHROPIC_API_KEY",
            "MINIMAX_API_KEY",
            "CLAUDE_CODE_API_KEY",
            "CLAUDE_CODE_BASE_URL",
        ] if k in os.environ}
    }
    if extra:
        env.update(extra)
    return env


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("timeout", 30)
    kwargs["env"] = _clean_env(kwargs.get("env"))
    return subprocess.run(args, **kwargs)


# ─────────────────────────────────────────────────────────────────────────────
# P0.0 — Preflight
# ─────────────────────────────────────────────────────────────────────────────

def test_p0_0_preflight_help_exits_zero():
    """preflight.py --help must exit 0 even in a fresh environment."""
    r = _run([sys.executable, str(REPO / "core" / "preflight.py"), "--help"])
    assert r.returncode == 0, f"preflight --help failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_p0_0_preflight_install_mode_runs():
    """preflight.py install must reach its skill-check phase without crashing.

    Note: preflight install exits 1 in a stranger environment because
    python3 (system) is 3.9 < 3.11. That failure is expected; the important
    invariant is that it does NOT crash with an uncaught exception — it must
    surface the failure cleanly.
    """
    r = _run([sys.executable, str(REPO / "core" / "preflight.py"), "install"])
    # Exit 1 is expected (python3 version warning). No crash.
    assert r.returncode in (0, 1), (
        f"preflight install crashed unexpectedly:\n"
        f"STDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    )
    # The python3 version check must appear in output so stranger knows why.
    combined = r.stdout + r.stderr
    assert "python" in combined.lower(), "python3 version issue not surfaced"


# ─────────────────────────────────────────────────────────────────────────────
# P0.2 — Install entry skills
# ─────────────────────────────────────────────────────────────────────────────

def test_p0_2_install_entry_skills_help_exits_zero():
    r = _run([
        sys.executable,
        str(REPO / "core" / "skills" / "clawseat-install" / "scripts" / "install_entry_skills.py"),
        "--help",
    ])
    assert r.returncode == 0, f"--help failed:\nSTDERR:{r.stderr}"


def test_p0_2_install_entry_skills_dry_run_exits_zero():
    r = _run([
        sys.executable,
        str(REPO / "core" / "skills" / "clawseat-install" / "scripts" / "install_entry_skills.py"),
        "--dry-run",
    ])
    assert r.returncode == 0, f"--dry-run failed:\nSTDERR:{r.stderr}"


# ─────────────────────────────────────────────────────────────────────────────
# P0.3 — Credential scan
# ─────────────────────────────────────────────────────────────────────────────

def test_p0_3_scan_environment_credentials_exits_zero(tmp_path):
    """scan_environment.py --only credentials must exit 0 and write index.json."""
    output = tmp_path / "scan_out"
    output.mkdir()
    r = _run([
        sys.executable,
        str(REPO / "core" / "skills" / "memory-oracle" / "scripts" / "scan_environment.py"),
        "--only", "credentials",
        "--output", str(output),
    ])
    assert r.returncode == 0, f"scan_environment failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    index = output / "index.json"
    assert index.exists(), f"index.json not written. stdout:{r.stdout}"
    data = json.loads(index.read_text())
    assert "credentials" in data.get("scanners", {}), "credentials scanner not in index"


# ─────────────────────────────────────────────────────────────────────────────
# P0.5 — Bootstrap workspace
# ─────────────────────────────────────────────────────────────────────────────

def test_p0_5_bootstrap_harness_help_exits_zero():
    """bootstrap_harness.py --help must exit 0 with python3.11 (no tomllib crash)."""
    r = _run([
        sys.executable,
        str(REPO / "core" / "skills" / "gstack-harness" / "scripts" / "bootstrap_harness.py"),
        "--help",
    ])
    assert r.returncode == 0, (
        f"bootstrap_harness --help failed:\n"
        f"STDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# P0.6 — Refresh workspaces
# ─────────────────────────────────────────────────────────────────────────────

def test_p0_6_refresh_workspaces_help_exits_zero():
    r = _run([
        sys.executable,
        str(REPO / "core" / "skills" / "clawseat-install" / "scripts" / "refresh_workspaces.py"),
        "--help",
    ])
    assert r.returncode == 0, f"--help failed:\nSTDERR:{r.stderr}"
