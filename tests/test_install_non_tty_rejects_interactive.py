from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "scripts" / "install.sh"


def test_non_tty_provider_selection_fails_with_clear_error(tmp_path: Path) -> None:
    """install.sh without --provider in non-TTY env exits 2 with provider guidance."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "PYTHON_BIN": sys.executable,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_BASE_URL": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "",
        "MINIMAX_API_KEY": "",
        "DASHSCOPE_API_KEY": "",
        "ARK_API_KEY": "",
    }
    with open(os.devnull, "rb") as devnull:
        result = subprocess.run(
            [
                "bash",
                str(INSTALL),
                "--project",
                "test-nontty",
                "--template",
                "clawseat-solo",
                "--force-repo-root",
                str(REPO),
            ],
            stdin=devnull,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )

    assert result.returncode == 2, result.stderr
    assert "NON_TTY_NO_PROVIDER" in result.stderr
    assert "--provider" in result.stderr
