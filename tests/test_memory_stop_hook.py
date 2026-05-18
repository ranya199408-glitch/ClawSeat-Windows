"""Tests for scripts/hooks/memory-stop-hook.sh.

These are subprocess-level contract tests for the upcoming Claude Code Stop
hook. The real hook receives a JSON payload on stdin; we model the minimal
Stop fields we care about (`transcript_path`, `stop_hook_active`,
`last_assistant_message`, etc.) and keep the payload shape aligned with the
official Claude Code hook docs.

Assumption: the hook resolves helper scripts relative to `CLAUDE_PROJECT_DIR`
when that env var is present. This keeps the tests portable while still
matching the expected repo-root execution model.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / "scripts" / "hooks" / "memory-stop-hook.sh"

pytestmark = pytest.mark.skipif(not _HOOK.exists(), reason="memory-stop-hook.sh not landed yet")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_wrapped_path(tmp_path: Path, *, tmux_rc: int = 0, python_rc: int = 0) -> tuple[Path, Path]:
    """Create PATH wrappers for tmux and python(3) that log invocations.

    The wrappers write one line per call to `calls.log` so the assertions can
    inspect the exact command line that the hook attempted to run.
    """

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "calls.log"
    real_python = sys.executable

    tmux_wrapper = """#!/usr/bin/env bash
set -eu
: "${CALLS_LOG:?}"
if [ "${1:-}" = "display-message" ]; then
  printf '%s\\n' "${TMUX_DISPLAY_MESSAGE:-mock-session}"
  exit 0
fi
printf 'tmux\\t%s\\n' "$*" >> "$CALLS_LOG"
exit "${TMUX_RC:-0}"
"""
    python_wrapper = f"""#!/usr/bin/env bash
set -eu
: "${{CALLS_LOG:?}}"
for arg in "$@"; do
  case "$arg" in
    *memory_deliver.py)
      printf 'python\\t%s\\n' "$*" >> "$CALLS_LOG"
      exit "${{PYTHON_RC:-0}}"
      ;;
  esac
done
exec {real_python!r} "$@"
"""

    _write_executable(bin_dir / "tmux", tmux_wrapper)
    _write_executable(bin_dir / "python", python_wrapper)
    _write_executable(bin_dir / "python3", python_wrapper)

    return bin_dir, calls_log


def _run_hook(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    tmux_rc: int = 0,
    python_rc: int = 0,
    transcript_content: str = "",
    session_id: str | None = "session-123",
    include_transcript_path: bool = True,
    raw_input: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the stop hook with PATH wrappers and return the process + log lines."""

    bin_dir, calls_log = _make_wrapped_path(tmp_path, tmux_rc=tmux_rc, python_rc=python_rc)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "CALLS_LOG": str(calls_log),
            "TMUX_RC": str(tmux_rc),
            "PYTHON_RC": str(python_rc),
            "TMUX_DISPLAY_MESSAGE": "install-memory-claude",
            "CLAUDE_PROJECT_DIR": str(_REPO),
            "HOME": str(home),
            "REAL_HOME": str(home),
            "CLAWSEAT_SEAT": "builder",
        }
    )
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(transcript_content, encoding="utf-8")
    payload = {
        "cwd": str(_REPO),
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        **payload,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    if include_transcript_path:
        payload["transcript_path"] = str(transcript)
    input_text = raw_input if raw_input is not None else json.dumps(payload, ensure_ascii=False) + "\n"
    proc = subprocess.run(
        ["bash", str(_HOOK)],
        input=input_text,
        text=True,
        capture_output=True,
        cwd=_REPO,
        env=env,
        check=False,
    )
    calls = calls_log.read_text(encoding="utf-8").splitlines() if calls_log.exists() else []
    return proc, calls


def test_clear_requested_triggers_tmux_send_keys(tmp_path: Path) -> None:
    """[CLEAR-REQUESTED] should fan out to tmux send-keys."""

    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "Work complete. [CLEAR-REQUESTED]",
        },
    )

    assert proc.returncode == 0
    tmux_calls = [line for line in calls if line.startswith("tmux\t")]
    assert tmux_calls
    assert "send-keys" in tmux_calls[0]
    assert "clear" in tmux_calls[0].lower()


def test_deliver_marker_triggers_memory_deliver_call(tmp_path: Path) -> None:
    """[DELIVER:seat=planner] should invoke memory_deliver.py via python."""

    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "Done. [DELIVER:seat=planner]",
        },
        transcript_content="task_id: MEMORY-QUERY-123\nproject: install\n",
    )

    assert proc.returncode == 0
    python_calls = [line for line in calls if line.startswith("python\t")]
    assert python_calls
    assert "memory_deliver.py" in python_calls[0]
    assert "planner" in python_calls[0]


def test_stop_hook_writes_active_session_marker(tmp_path: Path) -> None:
    proc, _calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "Done.",
        },
    )

    active_file = tmp_path / "home" / ".agent-runtime" / "active" / "builder.session"

    assert proc.returncode == 0
    assert active_file.read_text(encoding="utf-8").strip() == "session-123"


def test_no_marker_exits_zero_silently(tmp_path: Path) -> None:
    """No marker means no side effects, rc=0, and no stdout/stderr noise."""

    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "   \n\t  ",
        },
    )

    assert proc.returncode == 0
    assert calls == []
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_tmux_failure_still_exits_zero(tmp_path: Path) -> None:
    """tmux failures must be swallowed so the hook still exits successfully."""

    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "Wrap up. [CLEAR-REQUESTED]",
        },
        tmux_rc=1,
    )

    assert proc.returncode == 0
    tmux_calls = [line for line in calls if line.startswith("tmux\t")]
    assert tmux_calls
    assert "send-keys" in tmux_calls[0]


def test_invalid_json_exits_one_and_reports_error(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {},
        raw_input="{not-json",
    )

    assert proc.returncode == 1
    assert calls == []
    assert "invalid Stop payload JSON" in proc.stderr


def test_missing_transcript_path_exits_one(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "hello",
        },
        include_transcript_path=False,
    )

    assert proc.returncode == 1
    assert calls == []
    assert "transcript_path" in proc.stderr


def test_empty_session_id_exits_one(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "hello",
        },
        session_id="",
    )

    assert proc.returncode == 1
    assert calls == []
    assert "session_id" in proc.stderr
