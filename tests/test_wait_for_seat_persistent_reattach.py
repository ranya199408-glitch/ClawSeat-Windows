from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_wait_loop", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_WAIT_FOR_SEAT = _HELPERS._WAIT_FOR_SEAT
_write_executable = _HELPERS._write_executable


def test_wait_for_seat_reattaches_after_detach(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    attach_log = tmp_path / "attach.log"
    sleep_count = tmp_path / "sleep.count"

    _write_executable(
        bin_dir / "tmux",
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
    )
    _write_executable(
        bin_dir / "sleep",
        f"""#!/usr/bin/env bash
set -euo pipefail
count_file={sleep_count!s}
count=0
if [[ -f "$count_file" ]]; then
  count="$(cat "$count_file")"
fi
count=$((count + 1))
printf '%s' "$count" > "$count_file"
if [[ "$count" -ge 2 ]]; then
  kill -TERM "$PPID"
fi
exit 0
""",
    )
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

    result = subprocess.run(
        ["bash", str(_WAIT_FOR_SEAT), "spawn49", "planner"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "AGENTCTL_BIN": str(agentctl),
            "TMUX_MATCH_SESSION": "spawn49-planner",
            "WAIT_FOR_SEAT_POLL_SECONDS": "0.01",
            "WAIT_FOR_SEAT_RECONNECT_PAUSE": "0.01",
        },
        check=False,
        timeout=5,
    )

    assert result.returncode != 0
    attach_lines = attach_log.read_text(encoding="utf-8").splitlines()
    assert len(attach_lines) >= 2
    assert attach_lines[0] == "attach -t =spawn49-planner"
    assert attach_lines[1] == "attach -t =spawn49-planner"
    assert "DETACHED from spawn49-planner" in result.stdout


def test_wait_for_seat_rejects_retired_single_arg_interface(tmp_path: Path) -> None:
    result = subprocess.run(
        ["bash", str(_WAIT_FOR_SEAT), "spawn49-planner"],
        capture_output=True,
        text=True,
        env=os.environ,
        check=False,
        timeout=5,
    )

    assert result.returncode == 2
    assert "error: 1-arg form is retired; rerun as:" in result.stderr
