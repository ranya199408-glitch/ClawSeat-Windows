from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "send_delegation_report.py"


def _write_lark_cli_stub(
    bin_dir: Path,
    log_file: Path,
    *,
    auth_identity: str,
    env_log_file: Path | None = None,
) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "lark-cli"
    stub.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${{LARK_LOG_FILE:?}}"
if [[ -n "${{LARK_ENV_LOG_FILE:-}}" ]]; then
    printf 'cwd=%s\\n' "$PWD" >> "$LARK_ENV_LOG_FILE"
    printf 'OPENCLAW_HOME=%s\\n' "${{OPENCLAW_HOME:-<missing>}}" >> "$LARK_ENV_LOG_FILE"
fi
cmd="$*"
if [[ "$cmd" == "auth status" || "$cmd" == "--as user auth status" || "$cmd" == "--as bot auth status" ]]; then
    cat <<'JSON'
{{"identity":"{auth_identity}","tokenStatus":"valid","userName":"Tester"}}
JSON
elif [[ "$cmd" == "im +messages-send --chat-id "* ]] || [[ "$cmd" == "--as user im +messages-send --chat-id "* ]] || [[ "$cmd" == "--as bot im +messages-send --chat-id "* ]]; then
    printf 'sent\\n'
else
    echo "unexpected command: $*" >&2
    exit 1
fi
""",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    if os.name == "nt":
        cmd_stub = bin_dir / "lark-cli.cmd"
        cmd_stub.write_text(
            f"""@echo off
setlocal EnableDelayedExpansion
>> "%LARK_LOG_FILE%" echo %*
if not "%LARK_ENV_LOG_FILE%"=="" (
  >> "%LARK_ENV_LOG_FILE%" echo cwd=%CD%
  if "%OPENCLAW_HOME%"=="" (
    >> "%LARK_ENV_LOG_FILE%" echo OPENCLAW_HOME=^<missing^>
  ) else (
    >> "%LARK_ENV_LOG_FILE%" echo OPENCLAW_HOME=%OPENCLAW_HOME%
  )
)
set "cmd=%*"
if "!cmd!"=="auth status" goto auth
if "!cmd!"=="--as user auth status" goto auth
if "!cmd!"=="--as bot auth status" goto auth
echo !cmd! | findstr /B /C:"im +messages-send --chat-id" >nul && goto send
echo !cmd! | findstr /B /C:"--as user im +messages-send --chat-id" >nul && goto send
echo !cmd! | findstr /B /C:"--as bot im +messages-send --chat-id" >nul && goto send
echo unexpected command: %* 1>&2
exit /b 1
:auth
echo {{"identity":"{auth_identity}","tokenStatus":"valid","userName":"Tester"}}
exit /b 0
:send
echo sent
exit /b 0
""",
            encoding="utf-8",
        )


def _run_report(
    tmp_path: Path,
    *,
    identity: str,
    auth_identity: str,
    extra_args: list[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], list[str]]:
    real_home = tmp_path / "real_home"
    sandbox_home = tmp_path / "sandbox_home"
    real_home.mkdir(parents=True)
    sandbox_home.mkdir(parents=True)
    (real_home / ".openclaw").mkdir(parents=True, exist_ok=True)

    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "lark-cli.log"
    env_log_file = tmp_path / "lark-cli-env.log"
    _write_lark_cli_stub(bin_dir, log_file, auth_identity=auth_identity, env_log_file=env_log_file)

    args = [
        sys.executable,
        str(SCRIPT),
        "--project",
        "demo",
        "--lane",
        "builder",
        "--task-id",
        "task-1",
        "--report-status",
        "done",
        "--decision-hint",
        "proceed",
        "--user-gate",
        "none",
        "--next-action",
        "wait",
        "--summary",
        "hello world",
        "--chat-id",
        "<FEISHU_GROUP_ID>",
        "--as",
        identity,
    ]
    if extra_args:
        args.extend(extra_args)

    env = {
        **os.environ,
        "HOME": str(sandbox_home),
        "CLAWSEAT_REAL_HOME": str(real_home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "LARK_LOG_FILE": str(log_file),
        "LARK_ENV_LOG_FILE": str(env_log_file),
        "OPENCLAW_HOME": str(real_home / ".openclaw"),
    }
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    commands = log_file.read_text(encoding="utf-8").splitlines() if log_file.exists() else []
    env_lines = env_log_file.read_text(encoding="utf-8").splitlines() if env_log_file.exists() else []
    return result, commands, env_lines


def test_send_report_user_mode_passes_user_identity(tmp_path: Path) -> None:
    result, commands, _env_lines = _run_report(tmp_path, identity="user", auth_identity="user")

    assert result.returncode == 0, result.stderr
    # pre_check_auth=False: no auth-status pre-call; only the send command
    assert any(line.startswith("--as user im +messages-send") for line in commands)


def test_send_report_does_not_require_openclaw_home(tmp_path: Path) -> None:
    result, _commands, env_lines = _run_report(tmp_path, identity="auto", auth_identity="bot")

    assert result.returncode == 0, result.stderr
    assert any(line.startswith("cwd=") and line.endswith("real_home") for line in env_lines)
    assert "OPENCLAW_HOME=<missing>" in env_lines


def test_send_report_bot_mode_passes_bot_identity(tmp_path: Path) -> None:
    result, commands, _env_lines = _run_report(tmp_path, identity="bot", auth_identity="bot")

    assert result.returncode == 0, result.stderr
    # pre_check_auth=False: no auth-status pre-call; only the send command
    assert any(line.startswith("--as bot im +messages-send") for line in commands)


def test_send_report_auto_omits_as_flag(tmp_path: Path) -> None:
    result, commands, _env_lines = _run_report(tmp_path, identity="auto", auth_identity="bot")

    assert result.returncode == 0, result.stderr
    # pre_check_auth=False: no auth-status pre-call
    assert any(line.startswith("im +messages-send") and "--as" not in line for line in commands)


def test_check_auth_uses_requested_identity(tmp_path: Path) -> None:
    result, commands, _env_lines = _run_report(
        tmp_path,
        identity="bot",
        auth_identity="bot",
        extra_args=["--check-auth"],
    )

    assert result.returncode == 0, result.stderr
    assert commands == ["--as bot auth status"]
    assert '"requested_as": "bot"' in result.stdout
    assert '"status": "ok"' in result.stdout


def test_send_report_places_as_before_subcommand_for_all_identity_calls(tmp_path: Path) -> None:
    result, commands, _env_lines = _run_report(tmp_path, identity="user", auth_identity="user")

    assert result.returncode == 0, result.stderr
    assert commands
    # --as must precede the subcommand, not follow it
    assert all(not line.startswith("auth status --as") for line in commands)
    assert all(not line.startswith("im +messages-send --as") for line in commands)
    # pre_check_auth=False: first command is the send, not auth status
    assert any(line.startswith("--as user im +messages-send") for line in commands)
