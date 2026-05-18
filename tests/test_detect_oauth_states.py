from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


def _run_detect(command: str, home: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_ROOT": str(REPO),
        "CLAWSEAT_TEST_OSTYPE": "linux-gnu",
        "ANTHROPIC_API_KEY": "",
        "CLAUDE_API_KEY": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "",
        "OPENAI_API_KEY": "",
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
    }
    return subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; {command}"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_detect_oauth_states_reports_missing_then_ok(tmp_path: Path) -> None:
    """OAuth detection reads user-scoped auth files without requiring CLIs."""
    home = tmp_path / "home"
    home.mkdir()

    missing = _run_detect("detect_oauth_states", home)
    assert missing.returncode == 0, missing.stderr
    assert json.loads(missing.stdout) == {
        "claude": "missing",
        "codex": "missing",
        "gemini": "missing",
    }

    for relative in (
        ".claude/auth.json",
        ".codex/auth",
        ".gemini/oauth_creds.json",
    ):
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    detected = _run_detect("detect_oauth_states", home)
    assert detected.returncode == 0, detected.stderr
    assert json.loads(detected.stdout) == {
        "claude": "oauth",
        "codex": "oauth",
        "gemini": "oauth",
    }
