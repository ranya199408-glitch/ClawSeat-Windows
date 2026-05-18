"""Tests for scripts/hooks/planner-stop-hook.sh."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / "scripts" / "hooks" / "planner-stop-hook.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _make_lark_wrapper(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "calls.log"
    wrapper = """#!/usr/bin/env bash
set -eu
: "${CALLS_LOG:?}"
{
  printf 'lark\\t'
  printf '%q ' "$@"
  printf '\\n'
} >> "$CALLS_LOG"
exit 0
"""
    _write_executable(bin_dir / "lark-cli", wrapper)
    return bin_dir, calls_log


def _run_hook(
    tmp_path: Path,
    payload: dict[str, object],
    *,
    binding_text: str | None = None,
    project: str = "install",
    set_project_env: bool = True,
    planner_enabled: str = "1",
    install_lark: bool = True,
    workspace_project: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    home = tmp_path / "home"
    workspace_project = workspace_project or project
    workspace = home / ".agents" / "workspaces" / workspace_project / "planner"
    workspace.mkdir(parents=True, exist_ok=True)
    if binding_text is not None:
        binding_path = home / ".agents" / "tasks" / project / "PROJECT_BINDING.toml"
        binding_path.parent.mkdir(parents=True, exist_ok=True)
        binding_path.write_text(binding_text, encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "CLAUDE_PROJECT_DIR": str(workspace),
            "PYTHON_BIN": sys.executable,
            "PLANNER_STOP_HOOK_ENABLED": planner_enabled,
        }
    )
    if set_project_env:
        env["CLAWSEAT_PROJECT"] = project
    else:
        env.pop("CLAWSEAT_PROJECT", None)

    calls: list[str] = []
    if install_lark:
        bin_dir, calls_log = _make_lark_wrapper(tmp_path)
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        env["CALLS_LOG"] = str(calls_log)
    else:
        calls_log = tmp_path / "calls.log"
        env["PATH"] = "/usr/bin:/bin"

    proc = subprocess.run(
        ["bash", str(_HOOK)],
        input=json.dumps(payload, ensure_ascii=False) + "\n",
        text=True,
        capture_output=True,
        cwd=workspace,
        env=env,
        check=False,
    )
    if calls_log.exists():
        calls = calls_log.read_text(encoding="utf-8").splitlines()
    return proc, calls, workspace


def test_hook_disabled_exits_before_any_side_effect(tmp_path: Path) -> None:
    proc, calls, _ = _run_hook(
        tmp_path,
        {"last_assistant_message": "hello"},
        binding_text='project = "install"\nfeishu_group_id = "oc_test"\n',
        planner_enabled="0",
    )
    assert proc.returncode == 0
    assert calls == []
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_hook_missing_binding_skips_silently(tmp_path: Path) -> None:
    proc, calls, _ = _run_hook(
        tmp_path,
        {"last_assistant_message": "hello"},
        binding_text=None,
    )
    assert proc.returncode == 0
    assert calls == []
    assert "no PROJECT_BINDING.toml" in proc.stderr


def test_hook_missing_group_id_skips_silently(tmp_path: Path) -> None:
    proc, calls, _ = _run_hook(
        tmp_path,
        {"last_assistant_message": "hello"},
        binding_text='project = "install"\n',
    )
    assert proc.returncode == 0
    assert calls == []
    assert "no feishu_group_id" in proc.stderr


def test_hook_missing_lark_cli_skips_silently(tmp_path: Path) -> None:
    proc, calls, _ = _run_hook(
        tmp_path,
        {"last_assistant_message": "hello"},
        binding_text='project = "install"\nfeishu_group_id = "oc_test"\n',
        install_lark=False,
    )
    assert proc.returncode == 0
    assert calls == []
    assert "lark-cli not installed" in proc.stderr


def test_hook_infers_project_from_workspace_and_truncates_message(tmp_path: Path) -> None:
    long_message = "A" * 19050
    proc, calls, workspace = _run_hook(
        tmp_path,
        {
            "last_assistant_message": long_message,
            "cwd": str((tmp_path / "home" / ".agents" / "workspaces" / "install" / "planner")),
        },
        binding_text='project = "install"\nfeishu_group_id = "oc_test"\n',
        set_project_env=False,
    )
    assert proc.returncode == 0
    assert workspace.name == "planner"
    assert calls, "expected lark-cli send call"
    sent = calls[0]
    assert "im +messages-send" in sent
    assert "--chat-id oc_test" in sent
    assert "[planner@install]" in sent
    assert "...[omitted " in sent
