from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


@pytest.mark.parametrize("key", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
def test_detect_gemini_state_uses_google_api_keys(tmp_path: Path, key: str) -> None:
    """Gemini reports api_key for either Gemini or Google API key env vars."""
    home = tmp_path / "home"
    home.mkdir()
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
        key: "test-key",
    }
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_oauth_states"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["gemini"] == "api_key"
