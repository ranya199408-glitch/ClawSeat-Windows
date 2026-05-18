from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"
_ENGINEERING_TEMPLATE = _REPO / "templates" / "clawseat-engineering.toml"


def _run_dry(tmp_path: Path, *, opt_in: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "CLAWSEAT_REAL_HOME": str(tmp_path / "home"),
        "PYTHON_BIN": sys.executable,
    }
    if opt_in is not None:
        env["CLAWSEAT_PATROL_CRON_OPT_IN"] = opt_in
    return subprocess.run(
        [
            "bash",
            str(_INSTALL),
            "--dry-run",
            "--project",
            "qa-bootstrap",
            "--provider",
            "minimax",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_install_profile_includes_patrol() -> None:
    engineering = _ENGINEERING_TEMPLATE.read_text(encoding="utf-8")

    assert 'id = "patrol"' in engineering
    assert 'role = "patrol"' in engineering


def test_install_sh_invokes_install_patrol_hook(tmp_path: Path) -> None:
    result = _run_dry(tmp_path)
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "PENDING_SEATS=(planner builder reviewer patrol)" in combined
    assert "Step 7.6: install patrol hook + patrol cron" in combined
    assert "engineer create patrol qa-bootstrap --no-monitor" in combined
    assert "install_patrol_hook.py --workspace" in combined
    assert "/.agents/workspaces/qa-bootstrap/patrol" in combined


def test_install_sh_patrol_cron_optin_yes(tmp_path: Path) -> None:
    result = _run_dry(tmp_path, opt_in="y")
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "install_patrol_cron.py install" in combined
    assert "Patrol Cron installed" in combined


def test_install_sh_patrol_cron_optin_no(tmp_path: Path) -> None:
    result = _run_dry(tmp_path, opt_in="n")
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "install_patrol_cron.py install" not in combined
    assert "Patrol Cron skipped" in combined
