from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_wait", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_WAIT_FOR_SEAT = _HELPERS._WAIT_FOR_SEAT
_write_executable = _HELPERS._write_executable


def _run_wait_for_seat(tmp_path: Path, tmux_script: str, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_executable(bin_dir / "tmux", tmux_script)
    agentctl = tmp_path / "agentctl.sh"
    _write_executable(
        agentctl,
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "session-name" ]]; then
  printf '%s\\n' "${TMUX_MATCH_SESSION:?}"
fi
""",
    )
    _write_executable(
        bin_dir / "sleep",
        """#!/usr/bin/env bash
set -euo pipefail
kill -TERM "$PPID"
exit 0
""",
    )

    run_env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "AGENTCTL_BIN": str(agentctl),
        "WAIT_FOR_SEAT_POLL_SECONDS": "0.01",
        "WAIT_FOR_SEAT_RECONNECT_PAUSE": "0.01",
        **env,
    }
    return subprocess.run(
        ["bash", str(_WAIT_FOR_SEAT), "spawn49", "planner"],
        capture_output=True,
        text=True,
        env=run_env,
        check=False,
        timeout=5,
    )


def test_wait_for_seat_reports_trust_prompt_and_keeps_diagnostics(tmp_path: Path) -> None:
    result = _run_wait_for_seat(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  has-session)
    [[ "${3:-}" == "=${TMUX_MATCH_SESSION:?}" ]] && exit 0
    exit 1
    ;;
  attach)
    exit 1
    ;;
  capture-pane)
    printf '%s\\n' "Do you trust the files in this folder?"
    ;;
esac
""",
        env={"TMUX_MATCH_SESSION": "spawn49-planner"},
    )

    assert result.returncode != 0
    assert "gemini trust prompt detected at spawn49-planner - operator attach pane and press 1" in result.stderr


def test_wait_for_seat_attaches_when_session_is_ready(tmp_path: Path) -> None:
    attach_log = tmp_path / "attach.log"
    result = _run_wait_for_seat(
        tmp_path,
        f"""#!/usr/bin/env bash
set -euo pipefail
attach_log={attach_log!s}
case "$1" in
  has-session)
    [[ "${{3:-}}" == "=${{TMUX_MATCH_SESSION:?}}" ]] && exit 0
    exit 1
    ;;
  attach)
    printf '%s\\n' "$*" >> "$attach_log"
    exit 0
    ;;
  capture-pane)
    exit 1
    ;;
esac
""",
        env={"TMUX_MATCH_SESSION": "spawn49-planner"},
    )

    assert result.returncode != 0
    assert "DETACHED from spawn49-planner" in result.stdout
    assert attach_log.read_text(encoding="utf-8").strip() == "attach -t =spawn49-planner"
