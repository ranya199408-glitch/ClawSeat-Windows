from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "core" / "launchers" / "agent-launcher.sh"


def _launcher_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CLAWSEAT_REAL_HOME"] = str(home)
    return env


def test_deepseek_validate_auth_mode_accepted(tmp_path: Path) -> None:
    workdir = tmp_path / "work"
    workdir.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(LAUNCHER),
            "--tool",
            "claude",
            "--auth",
            "deepseek",
            "--dir",
            str(workdir),
            "--session",
            "deepseek-auth",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        env=_launcher_env(tmp_path / "home"),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "auth:     deepseek" in result.stdout


def test_deepseek_check_secrets_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = subprocess.run(
        ["bash", str(LAUNCHER), "--check-secrets", "claude", "--auth", "deepseek"],
        capture_output=True,
        text=True,
        env=_launcher_env(home),
        check=False,
    )
    payload = json.loads(result.stdout)
    expected = home / ".agent-runtime" / "secrets" / "claude" / "deepseek.env"
    assert result.returncode == 1
    assert payload["status"] == "missing-file"
    assert payload["file"] == str(expected)
    assert payload["key"] == "ANTHROPIC_AUTH_TOKEN"


def test_deepseek_resolve_secret_file_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    workdir = tmp_path / "work"
    workdir.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(LAUNCHER),
            "--tool",
            "claude",
            "--auth",
            "deepseek",
            "--dir",
            str(workdir),
            "--session",
            "deepseek-resolve",
            "--exec-agent",
        ],
        capture_output=True,
        text=True,
        env=_launcher_env(home),
        check=False,
    )
    expected = home / ".agent-runtime" / "secrets" / "claude" / "deepseek.env"
    assert result.returncode == 1
    assert f"missing Claude secret file: {expected}" in result.stderr
