from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_wait_stale_tool", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_WAIT_FOR_SEAT = _HELPERS._WAIT_FOR_SEAT
_write_executable = _HELPERS._write_executable


def _write_engineer_profile(home: Path, text: str | None) -> None:
    if text is None:
        return
    profile = home / ".agents" / "engineers" / "planner" / "engineer.toml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(text, encoding="utf-8")


def _run_wait_for_seat(
    tmp_path: Path,
    tmux_script: str,
    *,
    engineer_text: str | None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    home = tmp_path / "home"
    attach_log = tmp_path / "attach.log"
    sleep_count = tmp_path / "sleep.count"

    _write_engineer_profile(home, engineer_text)
    _write_executable(bin_dir / "tmux", tmux_script)
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
exit 0
""",
    )

    result = subprocess.run(
        ["bash", str(_WAIT_FOR_SEAT), "install", "planner"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "AGENTS_ROOT": str(home / ".agents"),
            "AGENTCTL_BIN": str(agentctl),
            "WAIT_FOR_SEAT_POLL_SECONDS": "0.01",
            "WAIT_FOR_SEAT_RECONNECT_PAUSE": "0.01",
            "WAIT_FOR_SEAT_PRIMARY_FAILURE_BUDGET": "1",
            "TMUX_ATTACH_LOG": str(attach_log),
        },
        check=False,
        timeout=5,
    )
    return result, attach_log


def test_wait_for_seat_skips_stale_tool_session_when_canonical_is_different(tmp_path: Path) -> None:
    result, attach_log = _run_wait_for_seat(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  has-session)
    [[ "${3:-}" == "=install-planner-codex" ]] && exit 0
    exit 1
    ;;
  attach)
    printf '%s\\n' "$*" >> "${TMUX_ATTACH_LOG:?}"
    exit 0
    ;;
  capture-pane)
    exit 1
    ;;
esac
""",
        engineer_text='id = "planner"\ndefault_tool = "claude"\n',
    )

    assert result.returncode != 0
    assert not attach_log.exists()
    assert "pane is waiting for install-planner" in result.stdout
    assert (
        "WARN: wait-for-seat stale-tool session detected: found install-planner-codex, "
        "canonical tool is claude, skipping"
    ) in result.stderr


def test_wait_for_seat_falls_back_to_canonical_tool_session_only(tmp_path: Path) -> None:
    result, attach_log = _run_wait_for_seat(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  has-session)
    [[ "${3:-}" == "=install-planner-claude" ]] && exit 0
    exit 1
    ;;
  attach)
    printf '%s\\n' "$*" >> "${TMUX_ATTACH_LOG:?}"
    exit 0
    ;;
  capture-pane)
    exit 1
    ;;
esac
""",
        engineer_text='id = "planner"\ndefault_tool = "claude"\n',
    )

    assert result.returncode != 0
    assert "WARN: wait-for-seat stale-tool session detected" not in result.stderr
    attach_lines = attach_log.read_text(encoding="utf-8").splitlines()
    assert attach_lines
    assert all(line == "attach -t =install-planner-claude" for line in attach_lines)


def test_wait_for_seat_prefers_canonical_tool_when_stale_variant_also_exists(tmp_path: Path) -> None:
    result, attach_log = _run_wait_for_seat(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  has-session)
    case "${3:-}" in
      "=install-planner-claude"|"=install-planner-codex")
        exit 0
        ;;
    esac
    exit 1
    ;;
  attach)
    printf '%s\\n' "$*" >> "${TMUX_ATTACH_LOG:?}"
    exit 0
    ;;
  capture-pane)
    exit 1
    ;;
esac
""",
        engineer_text='id = "planner"\ndefault_tool = "claude"\n',
    )

    assert result.returncode != 0
    assert (
        "WARN: wait-for-seat stale-tool session detected: found install-planner-codex, "
        "canonical tool is claude, skipping"
    ) in result.stderr
    attach_lines = attach_log.read_text(encoding="utf-8").splitlines()
    assert attach_lines
    assert all(line == "attach -t =install-planner-claude" for line in attach_lines)


@pytest.mark.parametrize(
    ("engineer_text", "reason"),
    [
        (None, "missing engineer profile"),
        ('id = "planner"\ndefault_tool = [\n', "malformed engineer profile"),
    ],
)
def test_wait_for_seat_keeps_waiting_when_engineer_profile_is_unusable(
    tmp_path: Path,
    engineer_text: str | None,
    reason: str,
) -> None:
    result, attach_log = _run_wait_for_seat(
        tmp_path,
        """#!/usr/bin/env bash
set -euo pipefail
case "$1" in
  has-session)
    [[ "${3:-}" == "=install-planner-claude" ]] && exit 0
    exit 1
    ;;
  attach)
    printf '%s\\n' "$*" >> "${TMUX_ATTACH_LOG:?}"
    exit 0
    ;;
  capture-pane)
    exit 1
    ;;
esac
""",
        engineer_text=engineer_text,
    )

    assert result.returncode != 0
    assert not attach_log.exists()
    assert "pane is waiting for install-planner" in result.stdout
    assert "WARN: wait-for-seat cannot resolve canonical tool for install-planner" in result.stderr
    assert reason in result.stderr
    assert "valid default_tool" in result.stderr
