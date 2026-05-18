from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_xcode", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_read_jsonl = _HELPERS._read_jsonl
_write_executable = _HELPERS._write_executable


def _write_xcode_scan_script(root: Path, *, api_key: str = "fixture-xcode-detected") -> None:
    _write_executable(
        root / "core" / "skills" / "memory-oracle" / "scripts" / "scan_environment.py",
        f"""#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--output", required=True)
args = parser.parse_args()
machine = Path(args.output) / "machine"
machine.mkdir(parents=True, exist_ok=True)
(machine / "credentials.json").write_text(json.dumps({{
    "keys": {{
        "ANTHROPIC_AUTH_TOKEN": {{"value": "{api_key}"}},
        "ANTHROPIC_BASE_URL": {{"value": "https://xcode.best"}},
    }},
    "oauth": {{"has_any": False}},
}}), encoding="utf-8")
for name in ("network", "openclaw", "github", "current_context"):
    (machine / f"{{name}}.json").write_text("{{}}", encoding="utf-8")
""",
    )


def _run_install(
    tmp_path: Path,
    *,
    project: str,
    args: list[str],
    input_text: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path, Path, Path]:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    if "xcode-best" in args:
        shared_secret = home / ".agent-runtime" / "secrets" / "claude" / "xcode-best.env"
        shared_secret.parent.mkdir(parents=True, exist_ok=True)
        shared_secret.write_text(
            "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\nANTHROPIC_BASE_URL=https://xcode.best\n",
            encoding="utf-8",
        )
    agent_admin_log = tmp_path / "agent_admin.jsonl"
    iterm_payload_log = tmp_path / "iterm_payload.jsonl"
    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            project,
            "--template",
            "clawseat-engineering",
            *args,
        ],
        input=input_text,
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
            "AGENT_ADMIN_LOG": str(agent_admin_log),
            "ITERM_PAYLOAD_LOG": str(iterm_payload_log),
        },
        check=False,
    )
    return result, home, launcher_log, root


def test_install_detects_xcode_best_candidate_and_auto_fills_base_url(tmp_path: Path) -> None:
    root, home, launcher_log, _tmux_log, py_stubs = _fake_install_root(tmp_path)
    agent_admin_log = tmp_path / "agent_admin.jsonl"
    iterm_payload_log = tmp_path / "iterm_payload.jsonl"
    _write_xcode_scan_script(root, api_key="xcode-fixture")
    shared_secret = home / ".agent-runtime" / "secrets" / "claude" / "xcode-best.env"
    shared_secret.parent.mkdir(parents=True, exist_ok=True)
    shared_secret.write_text(
        "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\nANTHROPIC_BASE_URL=https://xcode.best\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "xcodemenu50",
            "--template",
            "clawseat-engineering",
            "--all-api-provider",
            "xcode-best",
            "--provider",
            "1",
        ],
        input="1\n",
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
            "TMUX_LOG_FILE": str(_tmux_log),
            "AGENT_ADMIN_LOG": str(agent_admin_log),
            "ITERM_PAYLOAD_LOG": str(iterm_payload_log),
            "CLAWSEAT_TRUST_PROMPT_SLEEP_SECONDS": "0",
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "xcode-best" in combined
    assert "Provider URL will be auto-configured to https://xcode.best" in combined

    provider_env = (home / ".agents" / "tasks" / "xcodemenu50" / "memory-provider.env").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>" in provider_env
    assert "ANTHROPIC_BASE_URL=https://xcode.best" in provider_env

    planner_secret = (home / ".agents" / "secrets" / "claude" / "xcode-best" / "planner.env").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>" in planner_secret
    assert "ANTHROPIC_BASE_URL=https://xcode.best" in planner_secret

    records = _read_jsonl(launcher_log)
    assert [record["session"] for record in records] == ["xcodemenu50-memory-claude"]
    for record in records:
        assert record["custom_api_key_present"] is True
        assert record["custom_base_url"] == "https://xcode.best"
        assert record["custom_model"] == ""


def test_install_provider_xcode_best_with_api_key_auto_fills_base_url(tmp_path: Path) -> None:
    result, home, launcher_log, _root = _run_install(
        tmp_path,
        project="xcodeforce50",
        args=["--provider", "xcode-best", "--api-key", "fixture-xcode-force", "--all-api-provider", "xcode-best"],
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Using forced provider: xcode-best (base_url=https://xcode.best)" in combined
    assert "Provider URL will be auto-configured to https://xcode.best" in combined

    provider_env = (home / ".agents" / "tasks" / "xcodeforce50" / "memory-provider.env").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>" in provider_env
    assert "ANTHROPIC_BASE_URL=https://xcode.best" in provider_env

    planner_secret = (home / ".agents" / "secrets" / "claude" / "xcode-best" / "planner.env").read_text(encoding="utf-8")
    assert "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>" in planner_secret
    assert "ANTHROPIC_BASE_URL=https://xcode.best" in planner_secret

    records = _read_jsonl(launcher_log)
    assert [record["session"] for record in records] == ["xcodeforce50-memory-claude"]
    for record in records:
        assert record["custom_api_key_present"] is True
        assert record["custom_base_url"] == "https://xcode.best"
