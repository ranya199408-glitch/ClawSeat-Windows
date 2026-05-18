from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_survival", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_INSTALL = _HELPERS._INSTALL
_fake_install_root = _HELPERS._fake_install_root
_write_executable = _HELPERS._write_executable


def _tmux_survival_stub() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail
log="${TMUX_LOG_FILE:?}"
registry="${TMUX_LOG_FILE}.sessions"

target_from_args() {
  local target=""
  local i
  for ((i=1; i<=$#; i++)); do
    if [[ "${!i}" == "-t" ]]; then
      local j=$((i + 1))
      target="${!j:-}"
      break
    fi
  done
  printf '%s\n' "${target#=}"
}

case "${1:-}" in
  has-session)
    target="$(target_from_args "$@")"
    if [[ -f "$registry" ]] && grep -Fxq "$target" "$registry"; then
      exit 0
    fi
    exit 1
    ;;
  new-session)
    printf '%s\n' "$*" >> "$log"
    session=""
    saw_set_option=0
    saw_detach=0
    saw_off=0
    args=("$@")
    for ((i=0; i<${#args[@]}; i++)); do
      case "${args[i]}" in
        -s)
          session="${args[i+1]:-}"
          ;;
        set-option)
          saw_set_option=1
          ;;
        detach-on-destroy)
          saw_detach=1
          ;;
        off)
          saw_off=1
          ;;
      esac
    done
    if [[ -n "$session" && "$saw_set_option" == "1" && "$saw_detach" == "1" && "$saw_off" == "1" ]]; then
      printf '%s\n' "$session" >> "$registry"
    fi
    ;;
  set-option)
    printf '%s\n' "$*" >> "$log"
    target="$(target_from_args "$@")"
    if [[ -n "$target" ]] && [[ -f "$registry" ]] && grep -Fxq "$target" "$registry"; then
      exit 0
    fi
    exit 1
    ;;
  *)
    printf '%s\n' "$*" >> "$log"
    ;;
esac
"""


def _real_launcher_install_root(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    launcher_dir = root / "core" / "launchers"
    shutil.copy2(_REPO / "core" / "launchers" / "agent-launcher.sh", launcher_dir / "agent-launcher.sh")
    shutil.copy2(_REPO / "core" / "launchers" / "agent-launcher-common.sh", launcher_dir / "agent-launcher-common.sh")
    shutil.copy2(_REPO / "core" / "launchers" / "agent-launcher-discover.py", launcher_dir / "agent-launcher-discover.py")
    shutil.copytree(_REPO / "core" / "launchers" / "helpers", launcher_dir / "helpers")
    shutil.copytree(_REPO / "core" / "launchers" / "runtimes", launcher_dir / "runtimes")
    (launcher_dir / "agent-launcher.sh").chmod(0o755)
    (launcher_dir / "agent-launcher-common.sh").chmod(0o755)
    (launcher_dir / "agent-launcher-discover.py").chmod(0o755)

    bin_dir = tmp_path / "bin"
    _write_executable(bin_dir / "tmux", _tmux_survival_stub())
    return root, home, launcher_log, tmux_log, py_stubs


def test_install_launch_survives_session_create_with_early_detach_off(tmp_path: Path) -> None:
    root, home, _launcher_log, tmux_log, py_stubs = _real_launcher_install_root(tmp_path)

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "survive49",
            "--provider",
            "minimax",
        ],
        capture_output=True,
        text=True,
        timeout=40,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    tmux_output = tmux_log.read_text(encoding="utf-8")
    assert "new-session" in tmux_output
    assert "-s survive49-memory-claude" in tmux_output
    assert "-s machine-memory-claude" not in tmux_output
    assert "set-option -t survive49-memory-claude detach-on-destroy off" in tmux_output
    assert "set-option -t survive49-memory-claude status on" in tmux_output
    assert "set-option -t survive49-memory-claude status-style fg=white,bg=blue,bold" in tmux_output
