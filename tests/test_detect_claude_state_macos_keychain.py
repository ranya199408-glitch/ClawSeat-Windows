from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


def test_detect_claude_state_uses_macos_keychain(tmp_path: Path) -> None:
    """Claude Code v2.x OAuth is detected from the macOS Keychain service."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_security = bin_dir / "security"
    fake_security.write_text(
        """#!/usr/bin/env bash
if [[ "$*" == 'find-generic-password -s Claude Code-credentials -w' ]]; then
  printf 'token'
  exit 0
fi
exit 44
""",
        encoding="utf-8",
    )
    fake_security.chmod(fake_security.stat().st_mode | stat.S_IXUSR)

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_ROOT": str(REPO),
        "CLAWSEAT_TEST_OSTYPE": "darwin23",
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "ANTHROPIC_API_KEY": "",
        "CLAUDE_API_KEY": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
    }
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_oauth_states"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["claude"] == "oauth"


def test_detect_claude_state_uses_oauth_token_env(tmp_path: Path) -> None:
    """Claude Code OAuth token env var should map to oauth state."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_ROOT": str(REPO),
        "CLAWSEAT_TEST_OSTYPE": "linux-gnu",
        "ANTHROPIC_API_KEY": "",
        "CLAUDE_API_KEY": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "fixture-anthropic-oauth",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
    }
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_oauth_states"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["claude"] == "oauth"
