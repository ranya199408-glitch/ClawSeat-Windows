from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_provision_keys_writes_missing_keys_to_env_global(tmp_path: Path) -> None:
    home = tmp_path / "home"
    probe = f"""
set -euo pipefail
source "{_REPO / 'scripts' / 'install.sh'}" >/dev/null
_provision_missing_api_keys $'deepseek\\tDEEPSEEK_API_KEY\\nminimax\\tMINIMAX_API_KEY'
"""
    result = subprocess.run(
        ["bash", "-c", probe],
        input="ds-token\nmm-token\n",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHON_BIN": sys.executable,
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    env_text = (home / ".agents" / ".env.global").read_text(encoding="utf-8")
    assert "export DEEPSEEK_API_KEY=<DEEPSEEK_API_KEY>" in env_text
    assert "export MINIMAX_API_KEY=<MINIMAX_API_KEY>" in env_text
