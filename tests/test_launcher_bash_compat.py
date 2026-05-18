from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO / "core" / "launchers" / "agent-launcher.sh"
_BASH4_CASE_PATTERN = re.compile(r"\$\{[^}]*\^\^|\$\{[^}]*,,|\$\{[^}]*@U|\$\{[^}]*@L")


def test_launcher_has_no_bash4_case_conversion_syntax() -> None:
    text = _LAUNCHER.read_text(encoding="utf-8")
    assert _BASH4_CASE_PATTERN.search(text) is None


def test_launcher_help_runs_under_system_bash32(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/bash", str(_LAUNCHER), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--headless" in result.stdout


def test_launcher_dry_run_runs_under_system_bash32(tmp_path: Path) -> None:
    workdir = tmp_path / "workspace"
    workdir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "/bin/bash",
            str(_LAUNCHER),
            "--tool",
            "claude",
            "--auth",
            "oauth_token",
            "--session",
            "bash32-test",
            "--dir",
            str(workdir),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Unified launcher dry-run" in result.stdout

