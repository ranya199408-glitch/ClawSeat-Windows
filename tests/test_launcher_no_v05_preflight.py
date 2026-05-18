from __future__ import annotations

import os
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO / "core" / "launchers" / "agent-launcher.sh"


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        timeout=10,
    )


def test_launcher_source_no_longer_contains_v05_ancestor_preflight():
    text = _LAUNCHER.read_text()
    for needle in (
        "profile-dynamic.toml",
        "migrate_profile_to_v2.py",
        "patrol.plist.in",
        "_preflight_project",
        "--skip-ancestor-preflight",
        "--clone-from",
    ):
        assert needle not in text, f"launcher still references retired preflight artifact: {needle}"


def test_help_does_not_advertise_skip_ancestor_preflight():
    result = _run([str(_LAUNCHER), "--help"])
    assert result.returncode == 0
    assert "--skip-ancestor-preflight" not in result.stdout
    assert "--clone-from" not in result.stdout


def test_ancestor_session_dry_run_exits_zero_without_preflight_output():
    result = _run([
        str(_LAUNCHER),
        "--tool", "claude",
        "--auth", "oauth_token",
        "--session", "foo-ancestor-claude",
        "--dir", str(Path.home()),
        "--dry-run",
    ])
    assert result.returncode == 0, f"dry-run failed: {result.stderr}"
    combined = f"{result.stdout}\n{result.stderr}"
    assert "ancestor-preflight" not in combined
