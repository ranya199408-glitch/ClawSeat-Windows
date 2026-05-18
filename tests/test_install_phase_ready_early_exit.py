from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_ready", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_write_executable = _HELPERS._write_executable


def _write_ready_status(home: Path, project: str) -> Path:
    status_path = home / ".agents" / "tasks" / project / "STATUS.md"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text("phase=ready\nproviders=ancestor planner builder reviewer patrol designer memory\n", encoding="utf-8")
    return status_path


def test_install_exits_early_when_status_is_ready(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    _write_ready_status(home, "ready49")
    _write_executable(
        root / "core" / "preflight.py",
        """#!/usr/bin/env python3
raise SystemExit("preflight should not run when STATUS.md is already ready")
""",
    )

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "ready49",
            "--provider",
            "minimax",
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "already installed (phase=ready)" in combined
    assert "Use --reinstall or --force to rebuild." in combined
    assert not launcher_log.exists()
    assert not tmux_log.exists()


@pytest.mark.parametrize("reinstall_flag", ["--reinstall", "--force"])
def test_install_reinstall_flags_override_ready_status(tmp_path: Path, reinstall_flag: str) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    _write_ready_status(home, "ready50")

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            reinstall_flag,
            "--project",
            "ready50",
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
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "already installed" not in (result.stdout + result.stderr)
    tmux_output = tmux_log.read_text(encoding="utf-8")
    assert "set-option -t ready50-memory-claude detach-on-destroy off" in tmux_output
    assert "set-option -t machine-memory-claude detach-on-destroy off" not in tmux_output
