from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_status", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root


def test_install_sets_tmux_status_line_for_seat_sessions(tmp_path: Path) -> None:
    root, home, _launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "spawn49",
            "--provider",
            "minimax",
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
            "LOG_FILE": str(_launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    tmux_output = tmux_log.read_text(encoding="utf-8")
    assert "set-option -t spawn49-memory-claude status on" in tmux_output
    assert "set-option -t spawn49-memory-claude status-left [#{session_name}] " in tmux_output
    assert "set-option -t spawn49-memory-claude status-right #{?client_attached,ATTACHED,WAITING} | %H:%M" in tmux_output
    assert "set-option -t spawn49-memory-claude status-style fg=white,bg=blue,bold" in tmux_output
