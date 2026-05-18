"""Audit finding #11 — agent-launcher.sh load_shared_secrets injection.

Background: #6 (build_runtime injection in agent_admin_resolve.py) only
fires when build_runtime is called. start_engineer_launch builds env via
dict(os.environ) + CLAWSEAT_* keys directly and bypasses build_runtime
entirely, so #6 never reached the actual subprocess env that
agent-launcher.sh + the tool inherits.

Fix: load_shared_secrets() in agent-launcher.sh sources every
~/.agents/secrets/shared/*.env (or $CLAWSEAT_SHARED_SECRETS_DIR) BEFORE
runtimes/<tool>.sh sources the auth-tied secret. Auth-tied secrets thus
override the shared baseline, matching #6's "auth wins" semantics.

These tests use the launcher in CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY=1
mode so we can call load_shared_secrets without spawning a real tool.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "core" / "launchers" / "agent-launcher.sh"


def _bash_invoke_load_shared_secrets(
    tmp_path: Path, env_files: dict[str, str]
) -> dict[str, str]:
    """Run a bash that sources the launcher in library-only mode, calls
    load_shared_secrets, then prints the chosen keys from env."""
    shared = tmp_path / "secrets" / "shared"
    shared.mkdir(parents=True)
    for name, body in env_files.items():
        (shared / name).write_text(body, encoding="utf-8")

    script = f"""
set -euo pipefail
export CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY=1
export CLAWSEAT_SHARED_SECRETS_DIR={str(shared)!r}
export REAL_HOME={str(tmp_path)!r}
source {str(LAUNCHER)!r}
load_shared_secrets
echo "MINIMAX_API_KEY=${{MINIMAX_API_KEY:-UNSET}}"
echo "GEMINI_API_KEY=${{GEMINI_API_KEY:-UNSET}}"
echo "XCODE_BEST_GPT_IMAGE_API_KEY=${{XCODE_BEST_GPT_IMAGE_API_KEY:-UNSET}}"
echo "AUTH_TIED_KEY=${{AUTH_TIED_KEY:-UNSET}}"
echo "OVERRIDABLE=${{OVERRIDABLE:-UNSET}}"
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    out: dict[str, str] = {}
    for line in result.stdout.strip().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_load_shared_secrets_loads_env_files(tmp_path):
    """Files under shared/ are sourced and exported to launching tool."""
    env = _bash_invoke_load_shared_secrets(
        tmp_path,
        {
            "minimax.env": 'MINIMAX_API_KEY=<MINIMAX_API_KEY>\n',
            "gemini.env": 'GEMINI_API_KEY=<GEMINI_API_KEY>\n',
            "xcode-best.env": 'XCODE_BEST_GPT_IMAGE_API_KEY=<XCODE_BEST_GPT_IMAGE_API_KEY>\n',
        },
    )
    assert env["MINIMAX_API_KEY"] == "minimax-test-value-1"
    assert env["GEMINI_API_KEY"] == "gemini-test-value-2"
    assert env["XCODE_BEST_GPT_IMAGE_API_KEY"] == "xcb-test-value-3"


def test_load_shared_secrets_no_op_when_dir_missing(tmp_path):
    """Missing shared/ dir is silent; launcher continues launching."""
    # Don't create the dir; point at a non-existent path
    script = f"""
set -euo pipefail
export CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY=1
export CLAWSEAT_SHARED_SECRETS_DIR={str(tmp_path / 'nope')!r}
export REAL_HOME={str(tmp_path)!r}
source {str(LAUNCHER)!r}
load_shared_secrets
echo "ok"
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_load_shared_secrets_exports_so_subshell_inherits(tmp_path):
    """set -a wrapping means subshell inherits the loaded keys."""
    shared = tmp_path / "secrets" / "shared"
    shared.mkdir(parents=True)
    (shared / "test.env").write_text('TEST_KEY="hello"\n', encoding="utf-8")
    script = f"""
set -euo pipefail
export CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY=1
export CLAWSEAT_SHARED_SECRETS_DIR={str(shared)!r}
export REAL_HOME={str(tmp_path)!r}
source {str(LAUNCHER)!r}
load_shared_secrets
bash -c 'echo "subshell:$TEST_KEY"'
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "subshell:hello" in result.stdout


def test_load_shared_secrets_default_path_is_real_home_agents(tmp_path):
    """When CLAWSEAT_SHARED_SECRETS_DIR is unset, default is REAL_HOME/.agents/secrets/shared."""
    default_dir = tmp_path / ".agents" / "secrets" / "shared"
    default_dir.mkdir(parents=True)
    (default_dir / "default.env").write_text(
        'DEFAULT_PATH_KEY="<DEFAULT_PATH_KEY>"\n', encoding="utf-8"
    )
    script = f"""
set -euo pipefail
unset CLAWSEAT_SHARED_SECRETS_DIR
export CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY=1
export REAL_HOME={str(tmp_path)!r}
source {str(LAUNCHER)!r}
load_shared_secrets
echo "DEFAULT_PATH_KEY=${{DEFAULT_PATH_KEY:-UNSET}}"
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "DEFAULT_PATH_KEY=<DEFAULT_PATH_KEY>" in result.stdout


def test_load_shared_secrets_skips_non_env_files(tmp_path):
    """Only .env files are sourced; .txt / .md / no-ext files are skipped."""
    shared = tmp_path / "secrets" / "shared"
    shared.mkdir(parents=True)
    (shared / "real.env").write_text('REAL_KEY="loaded"\n', encoding="utf-8")
    (shared / "readme.txt").write_text("not env\n", encoding="utf-8")
    (shared / "notes.md").write_text("not env\n", encoding="utf-8")
    script = f"""
set -euo pipefail
export CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY=1
export CLAWSEAT_SHARED_SECRETS_DIR={str(shared)!r}
export REAL_HOME={str(tmp_path)!r}
source {str(LAUNCHER)!r}
load_shared_secrets
echo "REAL_KEY=${{REAL_KEY:-UNSET}}"
"""
    result = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True,
        env={**os.environ, "HOME": str(tmp_path)},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "REAL_KEY=loaded" in result.stdout
