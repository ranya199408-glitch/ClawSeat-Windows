from __future__ import annotations

import importlib.util
import os
import shlex
import subprocess
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_launcher_lark_cli_seed.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_launcher_lark_cli_seed_helpers_extra", _HELPERS_PATH)
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


def test_seed_user_tool_dirs_links_gemini_and_codex_user_dirs(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime" / "home"
    real_home.mkdir(parents=True)
    runtime_home.mkdir(parents=True)
    _seed_real_home(real_home)

    _run_seed_helper(real_home, runtime_home)

    for subpath in (
        ".config/gemini",
        ".gemini",
        ".config/codex",
        ".codex",
    ):
        link = runtime_home / subpath
        assert link.is_symlink()
        assert link.readlink() == real_home / subpath

    (runtime_home / ".config" / "gemini" / "roundtrip.txt").write_text("g", encoding="utf-8")
    (runtime_home / ".codex" / "roundtrip.txt").write_text("c", encoding="utf-8")

    assert (real_home / ".config" / "gemini" / "roundtrip.txt").read_text(encoding="utf-8") == "g"
    assert (real_home / ".codex" / "roundtrip.txt").read_text(encoding="utf-8") == "c"
