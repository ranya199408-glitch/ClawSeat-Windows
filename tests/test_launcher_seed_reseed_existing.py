from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_launcher_lark_cli_seed.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_launcher_lark_cli_seed_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

LAUNCHER = _HELPERS.LAUNCHER
_seed_real_home = _HELPERS._seed_real_home


def _run_seed_helper(real_home: Path, runtime_home: Path) -> None:
    env = {
        **os.environ,
        "HOME": str(real_home),
        "CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY": "1",
    }
    snippet = "\n".join(
        [
            "set -euo pipefail",
            f"source {shlex.quote(str(LAUNCHER))}",
            f"seed_user_tool_dirs {shlex.quote(str(runtime_home))}",
        ]
    )
    result = subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_seed_user_tool_dirs_reseeds_existing_sandbox_targets_with_backups(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime" / "home"
    real_home.mkdir(parents=True)
    runtime_home.mkdir(parents=True)
    _seed_real_home(real_home)

    sandbox_lark = runtime_home / ".lark-cli"
    sandbox_lark.mkdir(parents=True)
    (sandbox_lark / "sentinel.txt").write_text("keep-me", encoding="utf-8")

    sandbox_gemini = runtime_home / ".config" / "gemini"
    sandbox_gemini.mkdir(parents=True)
    (sandbox_gemini / "sentinel.txt").write_text("gemini-keep", encoding="utf-8")

    sandbox_codex = runtime_home / ".codex"
    sandbox_codex.mkdir(parents=True)
    (sandbox_codex / "sentinel.txt").write_text("codex-keep", encoding="utf-8")

    _run_seed_helper(real_home, runtime_home)

    assert sandbox_lark.is_symlink()
    assert sandbox_lark.readlink() == real_home / ".lark-cli"
    assert sandbox_gemini.is_symlink()
    assert sandbox_gemini.readlink() == real_home / ".config" / "gemini"
    assert sandbox_codex.is_symlink()
    assert sandbox_codex.readlink() == real_home / ".codex"

    backup_root = runtime_home / ".sandbox-pre-seed-backup"
    backups = list(backup_root.rglob("sentinel.txt"))
    assert backups, "expected sandbox backup copies to be written"
    assert any(path.read_text(encoding="utf-8") == "keep-me" for path in backups)
    assert any(path.read_text(encoding="utf-8") == "gemini-keep" for path in backups)
    assert any(path.read_text(encoding="utf-8") == "codex-keep" for path in backups)
