from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


def test_detect_claude_json_oauth_account_requires_exact_field(tmp_path: Path) -> None:
    """Claude JSON detection matches oauthAccount, not loose oauth text."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text('{"notOauthAccount": true}', encoding="utf-8")
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

    missing = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_oauth_states"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert missing.returncode == 0, missing.stderr
    assert json.loads(missing.stdout)["claude"] == "missing"

    (home / ".claude.json").write_text('{"oauthAccount": {"email": "a@example.invalid"}}', encoding="utf-8")
    detected = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_oauth_states"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert detected.returncode == 0, detected.stderr
    assert json.loads(detected.stdout)["claude"] == "oauth"
