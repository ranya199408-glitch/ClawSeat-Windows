from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_provider_choice", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_read_jsonl = _HELPERS._read_jsonl
_write_executable = _HELPERS._write_executable


def _write_multi_candidate_scan_script(root: Path) -> None:
    _write_executable(
        root / "core" / "skills" / "memory-oracle" / "scripts" / "scan_environment.py",
        """#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()
machine = Path(args.output) / "machine"
machine.mkdir(parents=True, exist_ok=True)
machine_creds = {
    "keys": {
        "MINIMAX_API_KEY": {"value": "<MINIMAX_TOKEN>"},
        "MINIMAX_BASE_URL": {"value": "https://api.minimaxi.com/anthropic"},
        "CLAUDE_CODE_OAUTH_TOKEN": {"value": "oauth-token"},
        "ARK_API_KEY": {"value": "<ARK_TOKEN>"},
        "ARK_BASE_URL": {"value": "https://ark.cn-beijing.volces.com/api/coding"},
    },
    "oauth": {"has_any": False},
}
(machine / "credentials.json").write_text(json.dumps(machine_creds), encoding="utf-8")
for name in ("network", "openclaw", "github", "current_context"):
    (machine / f"{name}.json").write_text("{}", encoding="utf-8")
""",
    )


def _run_install_with_choice(
    tmp_path: Path,
    *,
    project: str,
    extra_args: list[str],
    extra_env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path, Path]:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    _write_multi_candidate_scan_script(root)
    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"), *extra_args, "--project", project],
        input="",
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
            **extra_env,
        },
        check=False,
    )
    return result, root, home, launcher_log, tmux_log


def test_install_provider_choice_env_var_selects_first_candidate_without_tty(tmp_path: Path) -> None:
    result, _root, home, launcher_log, tmux_log = _run_install_with_choice(
        tmp_path,
        project="choice49",
        extra_args=[],
        extra_env={"CLAWSEAT_INSTALL_PROVIDER": "1"},
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Using selected provider candidate #1" in combined

    provider_env = (home / ".agents" / "tasks" / "choice49" / "memory-provider.env").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>" in provider_env
    assert "ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic" in provider_env
    assert "ANTHROPIC_MODEL=MiniMax-M2.7-highspeed" in provider_env

    records = _read_jsonl(launcher_log)
    assert records[0]["custom_base_url"] == "https://api.minimaxi.com/anthropic"
    assert records[0]["custom_model"] == "MiniMax-M2.7-highspeed"
    assert "set-option -t choice49-memory-claude detach-on-destroy off" in tmux_log.read_text(encoding="utf-8")


def test_install_provider_choice_flag_selects_first_candidate_without_tty(tmp_path: Path) -> None:
    result, _root, home, launcher_log, tmux_log = _run_install_with_choice(
        tmp_path,
        project="choice50",
        extra_args=["--provider", "1"],
        extra_env={},
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Using selected provider candidate #1" in combined

    provider_env = (home / ".agents" / "tasks" / "choice50" / "memory-provider.env").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>" in provider_env
    assert "ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic" in provider_env
    assert "ANTHROPIC_MODEL=MiniMax-M2.7-highspeed" in provider_env

    records = _read_jsonl(launcher_log)
    assert records[0]["custom_base_url"] == "https://api.minimaxi.com/anthropic"
    assert records[0]["custom_model"] == "MiniMax-M2.7-highspeed"
    assert "set-option -t choice50-memory-claude detach-on-destroy off" in tmux_log.read_text(encoding="utf-8")
