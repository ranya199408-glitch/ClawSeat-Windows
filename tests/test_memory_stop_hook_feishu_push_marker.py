from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "hooks" / "memory-stop-hook.sh"

pytestmark = pytest.mark.skipif(not HOOK.exists(), reason="memory-stop-hook.sh not landed yet")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_wrappers(tmp_path: Path, *, tmux_rc: int = 0, python_rc: int = 0) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "calls.log"
    real_python = sys.executable

    tmux_wrapper = """#!/usr/bin/env bash
set -eu
: "${CALLS_LOG:?}"
if [ "${1:-}" = "display-message" ]; then
  printf '%s\n' "${TMUX_DISPLAY_MESSAGE:-mock-session}"
  exit 0
fi
printf 'tmux\t%s\n' "$*" >> "$CALLS_LOG"
exit "${TMUX_RC:-0}"
"""
    lark_wrapper = """#!/usr/bin/env bash
set -eu
: "${CALLS_LOG:?}"
python3 - "$@" <<'PY'
import json
import os
import sys

with open(os.environ["CALLS_LOG"], "a", encoding="utf-8") as handle:
    handle.write("lark\t")
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False))
    handle.write("\n")
PY
exit "${LARK_CLI_RC:-0}"
"""
    python_wrapper = f"""#!/usr/bin/env bash
set -eu
: "${{CALLS_LOG:?}}"
case "$*" in
  *memory_deliver.py*)
    printf 'python\t%s\n' "$*" >> "$CALLS_LOG"
    exit "${{PYTHON_RC:-0}}"
    ;;
esac
exec {real_python!r} "$@"
"""

    _write_executable(bin_dir / "tmux", tmux_wrapper)
    _write_executable(bin_dir / "lark-cli", lark_wrapper)
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
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir, calls_log = _make_wrappers(tmp_path, tmux_rc=tmux_rc, python_rc=python_rc)
    home = tmp_path / "home"
    binding = home / ".agents" / "tasks" / "install" / "PROJECT_BINDING.toml"
    binding.parent.mkdir(parents=True, exist_ok=True)
    binding.write_text('project = "install"\nfeishu_group_id = "<FEISHU_GROUP_ID>"\n', encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "HOME": str(home),
            "CALLS_LOG": str(calls_log),
            "TMUX_RC": str(tmux_rc),
            "PYTHON_RC": str(python_rc),
            "CLAWSEAT_PROJECT": "install",
            "AGENTS_PROJECT": "install",
            "TMUX_DISPLAY_MESSAGE": "install-memory-claude",
            "CLAUDE_PROJECT_DIR": str(REPO),
            "LARK_CLI_RC": "0",
            "CLAWSEAT_FEISHU_ENABLED": "1",
        }
    )
    if extra_env:
        env.update(extra_env)

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(transcript_content, encoding="utf-8")

    payload = {
        "session_id": "session-123",
        "transcript_path": str(transcript),
        "cwd": str(REPO),
        "permission_mode": "default",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        **payload,
    }
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload, ensure_ascii=False) + "\n",
        text=True,
        capture_output=True,
        cwd=REPO,
        env=env,
        check=False,
    )
    calls = calls_log.read_text(encoding="utf-8").splitlines() if calls_log.exists() else []
    return proc, calls


def _feishu_send_text(calls: list[str]) -> str:
    for index, line in enumerate(calls):
        if not line.startswith("--as user im +messages-send "):
            continue
        if " --text " not in line:
            continue
        text = line.split(" --text ", 1)[1]
        parts = [text]
        for tail in calls[index + 1 :]:
            if tail.startswith(("python\t", "tmux\t", "--as user im +messages-send ")):
                break
            parts.append(tail)
        return "\n".join(parts)
    raise AssertionError("No Feishu send recorded")


def test_memory_stop_hook_auto_pushes_plain_text_via_lark_cli(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "Natural-language update from the TUI.",
        },
    )

    assert proc.returncode == 0, proc.stderr
    assert any(line.startswith("--as user im +messages-send ") for line in calls)
    content = _feishu_send_text(calls)
    assert content.startswith("[Memory] Natural-language update from the TUI.")
    assert "\n---\n_via Memory @" in content
    assert "project=install" in content
    assert "session=install-memory-claude" in content


def test_memory_stop_hook_includes_task_context_in_footer(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": (
                "Natural-language update. "
                "[DELIVER:seat=planner task_id=MEMORY-QUERY-123 verdict=PASS summary=清洗流水线]"
            ),
        },
        transcript_content="task_id: MEMORY-QUERY-123\nproject: install\n",
    )

    assert proc.returncode == 0, proc.stderr
    assert any(line.startswith("python\t") for line in calls)

    content = _feishu_send_text(calls)
    assert content.startswith("[Memory] Natural-language update.")
    assert "task_id=MEMORY-QUERY-123" in content
    assert "verdict=PASS" in content


def test_memory_stop_hook_truncates_long_push_text(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "x" * 3600,
        },
    )

    assert proc.returncode == 0, proc.stderr

    content = _feishu_send_text(calls)
    assert content.startswith("[Memory] ")
    assert "…[truncated, see TUI]" in content
    assert len(content) < 4096


def test_memory_stop_hook_skips_feishu_when_disabled(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "Natural-language update that should stay local.",
        },
        extra_env={"CLAWSEAT_FEISHU_ENABLED": "0"},
    )

    assert proc.returncode == 0, proc.stderr
    assert not any(line.startswith("--as user im +messages-send ") for line in calls)


def test_memory_stop_hook_path_b_delivers_without_feishu_push(tmp_path: Path) -> None:
    proc, calls = _run_hook(
        tmp_path,
        {
            "last_assistant_message": "[DELIVER:seat=planner task_id=MEMORY-QUERY-999 verdict=PASS summary=清洗流水线]",
        },
        transcript_content="task_id: MEMORY-QUERY-999\nproject: install\n",
    )

    assert proc.returncode == 0, proc.stderr
    python_calls = [line for line in calls if line.startswith("python\t")]
    assert python_calls
    assert "memory_deliver.py" in python_calls[0]
    assert "planner" in python_calls[0]
    assert not any(line.startswith("--as user im +messages-send ") for line in calls)
