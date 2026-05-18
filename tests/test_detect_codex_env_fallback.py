from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


def test_detect_codex_state_uses_openai_api_key(tmp_path: Path) -> None:
    """Codex reports api_key when OPENAI_API_KEY is available."""
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
        "OPENAI_API_KEY": "<API_KEY>",
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
    assert json.loads(result.stdout)["codex"] == "api_key"
