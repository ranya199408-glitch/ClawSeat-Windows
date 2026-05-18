from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_read_jsonl = _HELPERS._read_jsonl
_write_executable = _HELPERS._write_executable


def test_install_skips_iterm_gui_in_sandbox_home(tmp_path: Path) -> None:
    root, real_home, launcher_log, tmux_log, _py_stubs = _fake_install_root(tmp_path)
    sandbox_home = tmp_path / ".agents" / "runtime" / "identities" / "claude" / "api" / "sandbox" / "home"
    sandbox_home.mkdir(parents=True, exist_ok=True)
    iterm_payload_log = tmp_path / "iterm_payload.jsonl"
    (root / "core" / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(__file__).resolve().parents[1] / "core" / "lib" / "real_home.py", root / "core" / "lib" / "real_home.py")
    _write_executable(
        root.parent / "bin" / "uname",
        """#!/usr/bin/env bash
printf 'Linux\\n'
""",
    )

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "sandbox49",
            "--provider",
            "minimax",
        ],
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(sandbox_home),
            "CLAWSEAT_REAL_HOME": str(real_home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "ITERM_PAYLOAD_LOG": str(iterm_payload_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "WARN: Skipping iTerm window open in sandbox/headless install: native iTerm panes require macOS." in result.stderr
    assert "WARN: Skipping primary seat focus because no iTerm grid window was opened." in result.stderr
    assert "ClawSeat install complete" in result.stdout
    assert not iterm_payload_log.exists()

    records = _read_jsonl(launcher_log)
    assert [record["session"] for record in records] == ["sandbox49-memory-claude"]
