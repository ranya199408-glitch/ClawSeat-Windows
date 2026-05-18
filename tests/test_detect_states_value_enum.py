from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "scripts" / "install.sh"
ALLOWED = {"oauth", "api_key", "missing"}


def test_detect_all_oauth_values_use_strict_enum(tmp_path: Path) -> None:
    """detect_all never emits the deprecated ok value for auth states."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "CLAWSEAT_TEST_OSTYPE": "linux-gnu",
        "PYTHON_BIN": sys.executable,
        "ANTHROPIC_API_KEY": "fixture-anthropic",
        "CLAUDE_API_KEY": "",
        "OPENAI_API_KEY": "fixture-openai",
        "GEMINI_API_KEY": "gemini-test",
        "GOOGLE_API_KEY": "",
    }
    result = subprocess.run(
        [
            "bash",
            str(INSTALL),
            "--detect-only",
            "--force-repo-root",
            str(REPO),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    states = json.loads(result.stdout)["oauth"]
    assert set(states.values()) <= ALLOWED
    assert "ok" not in states.values()
