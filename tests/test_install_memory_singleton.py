from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_read_jsonl = _HELPERS._read_jsonl
_write_executable = _HELPERS._write_executable


def _write_tmux_stub(bin_dir: Path, *, has_memory_session: bool) -> None:
    _write_executable(
        bin_dir / "tmux",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "has-session" ]]; then
  target="${{3:-}}"
  target="${{target#=}}"
  registry="${{TMUX_LOG_FILE:-}}.sessions"
  if [[ -n "${{TMUX_LOG_FILE:-}}" && -f "$registry" ]] && grep -Fxq "$target" "$registry"; then
    exit 0
  fi
  if [[ "$target" == "machine-memory-claude" ]]; then
    exit {"0" if has_memory_session else "1"}
  fi
  exit 1
fi
printf '%s\\n' "$*" >> "${{TMUX_LOG_FILE:?}}"
""",
    )


def _write_osascript_stub(bin_dir: Path, *, has_memory_window: bool) -> None:
    _write_executable(
        bin_dir / "osascript",
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' '{"1" if has_memory_window else "0"}'
""",
    )


def _run_install(
    tmp_path: Path,
    *,
    project: str,
    has_memory_session: bool,
    has_memory_window: bool,
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    bin_dir = tmp_path / "bin"
    agent_admin_log = tmp_path / "agent_admin.jsonl"
    iterm_payload_log = tmp_path / "iterm_payload.jsonl"
    _write_tmux_stub(bin_dir, has_memory_session=has_memory_session)
    _write_osascript_stub(bin_dir, has_memory_window=has_memory_window)

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            project,
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
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "AGENT_ADMIN_LOG": str(agent_admin_log),
            "ITERM_PAYLOAD_LOG": str(iterm_payload_log),
        },
        check=False,
    )
    return result, launcher_log, tmux_log, iterm_payload_log, root


def test_install_ignores_existing_legacy_memory_daemon_and_window(tmp_path: Path) -> None:
    result, launcher_log, tmux_log, iterm_payload_log, _ = _run_install(
        tmp_path,
        project="singleton50",
        has_memory_session=True,
        has_memory_window=True,
    )

    assert result.returncode == 0, result.stderr
    assert "memory seat already running (machine-memory-claude), reusing." not in result.stdout
    assert "memory iTerm window already open, skipping open." not in result.stdout

    records = _read_jsonl(launcher_log)
    assert [record["session"] for record in records] == ["singleton50-memory-claude"]

    tmux_log_text = tmux_log.read_text(encoding="utf-8")
    assert "kill-session -t =machine-memory-claude" not in tmux_log_text
    assert "set-option -t machine-memory-claude" not in tmux_log_text

    payloads = _read_jsonl(iterm_payload_log)
    assert [payload["title"] for payload in payloads] == [
        "clawseat-singleton50-workers",
        "clawseat-memories",
    ]


def test_install_does_not_start_legacy_memory_daemon_when_missing(tmp_path: Path) -> None:
    result, launcher_log, _, iterm_payload_log, _ = _run_install(
        tmp_path,
        project="singleton51",
        has_memory_session=False,
        has_memory_window=False,
    )

    assert result.returncode == 0, result.stderr

    records = _read_jsonl(launcher_log)
    assert [record["session"] for record in records] == ["singleton51-memory-claude"]

    payloads = _read_jsonl(iterm_payload_log)
    assert [payload["title"] for payload in payloads] == [
        "clawseat-singleton51-workers",
        "clawseat-memories",
    ]


def test_install_memory_hook_is_noop_when_existing(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "install_memory_hook_module",
        _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "install_memory_hook.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    workspace = tmp_path / "workspace"
    hook_script = tmp_path / "memory-stop-hook.sh"
    hook_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    settings_path = workspace / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        '{\n'
        '  "hooks": {\n'
        '    "Stop": [\n'
        '      {\n'
        '        "matcher": "",\n'
        '        "hooks": [\n'
        f'          {{"type": "command", "command": "bash {hook_script}", "timeout": 10}}\n'
        "        ]\n"
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )

    _, settings, changed = module.install_memory_hook(workspace, hook_script)

    assert changed is False
    stop_entries = settings["hooks"]["Stop"]
    assert len(stop_entries) == 1
    assert stop_entries[0]["hooks"][0]["command"] == f"bash {hook_script}"
