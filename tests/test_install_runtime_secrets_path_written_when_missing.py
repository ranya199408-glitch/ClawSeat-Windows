from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_runtime_missing_helpers", HELPERS_PATH)
assert HELPERS_SPEC is not None and HELPERS_SPEC.loader is not None
HELPERS = importlib.util.module_from_spec(HELPERS_SPEC)
HELPERS_SPEC.loader.exec_module(HELPERS)

_fake_install_root = HELPERS._fake_install_root


def test_runtime_claude_provider_env_written_when_missing(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    runtime_secret = home / ".agent-runtime" / "secrets" / "claude" / "minimax.env"
    assert not runtime_secret.exists()
    real_token = "sk-" + "M" * 24

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "runtime-missing",
            "--template",
            "clawseat-creative",
            "--provider",
            "minimax",
            "--api-key",
            real_token,
        ],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert runtime_secret.is_file()
    assert f"ANTHROPIC_AUTH_TOKEN={real_token}" in runtime_secret.read_text(encoding="utf-8")
    patrol_secret = home / ".agents" / "secrets" / "claude" / "minimax" / "patrol.env"
    assert patrol_secret.is_file()
    assert f"ANTHROPIC_AUTH_TOKEN={real_token}" in patrol_secret.read_text(encoding="utf-8")
