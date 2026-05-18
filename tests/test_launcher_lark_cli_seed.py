from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "core" / "launchers" / "agent-launcher.sh"


def _seed_real_home(real_home: Path) -> None:
    lark_cli_home = real_home / ".lark-cli"
    lark_cli_home.mkdir(parents=True, exist_ok=True)
    (lark_cli_home / "config.json").write_text('{"loggedIn": true}', encoding="utf-8")

    iterm_dir = real_home / "Library" / "Application Support" / "iTerm2"
    iterm_dir.mkdir(parents=True, exist_ok=True)
    (iterm_dir / "state.txt").write_text("shared-state", encoding="utf-8")

    prefs = real_home / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
    prefs.parent.mkdir(parents=True, exist_ok=True)
    prefs.write_text("prefs=1", encoding="utf-8")

    gemini_cfg = real_home / ".config" / "gemini"
    gemini_cfg.mkdir(parents=True, exist_ok=True)
    (gemini_cfg / "settings.json").write_text("gemini-settings", encoding="utf-8")

    gemini_home = real_home / ".gemini"
    gemini_home.mkdir(parents=True, exist_ok=True)
    (gemini_home / "auth.json").write_text("gemini-auth", encoding="utf-8")

    codex_cfg = real_home / ".config" / "codex"
    codex_cfg.mkdir(parents=True, exist_ok=True)
    (codex_cfg / "config.toml").write_text("model = 'gpt-5.4'", encoding="utf-8")

    codex_home = real_home / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "auth.json").write_text("codex-auth", encoding="utf-8")


def _seed_lark_only_home(real_home: Path) -> None:
    lark_cli_home = real_home / ".lark-cli"
    lark_cli_home.mkdir(parents=True, exist_ok=True)
    (lark_cli_home / "config.json").write_text('{"loggedIn": true}', encoding="utf-8")


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


def test_seed_user_tool_dirs_links_existing_sources_and_shares_writes(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime" / "home"
    real_home.mkdir(parents=True)
    runtime_home.mkdir(parents=True)
    _seed_real_home(real_home)

    _run_seed_helper(real_home, runtime_home)

    lark_link = runtime_home / ".lark-cli"
    iterm_link = runtime_home / "Library" / "Application Support" / "iTerm2"
    prefs_link = runtime_home / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
    gemini_cfg_link = runtime_home / ".config" / "gemini"
    gemini_home_link = runtime_home / ".gemini"
    codex_cfg_link = runtime_home / ".config" / "codex"
    codex_home_link = runtime_home / ".codex"

    assert lark_link.is_symlink()
    assert lark_link.readlink() == real_home / ".lark-cli"
    assert iterm_link.is_symlink()
    assert iterm_link.readlink() == real_home / "Library" / "Application Support" / "iTerm2"
    assert prefs_link.is_symlink()
    assert prefs_link.readlink() == real_home / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
    assert gemini_cfg_link.is_symlink()
    assert gemini_cfg_link.readlink() == real_home / ".config" / "gemini"
    assert gemini_home_link.is_symlink()
    assert gemini_home_link.readlink() == real_home / ".gemini"
    assert codex_cfg_link.is_symlink()
    assert codex_cfg_link.readlink() == real_home / ".config" / "codex"
    assert codex_home_link.is_symlink()
    assert codex_home_link.readlink() == real_home / ".codex"

    (lark_link / "roundtrip.txt").write_text("lark-write", encoding="utf-8")
    (iterm_link / "roundtrip.txt").write_text("iterm-write", encoding="utf-8")
    prefs_link.write_text("prefs-updated", encoding="utf-8")
    (gemini_cfg_link / "roundtrip.txt").write_text("gemini-write", encoding="utf-8")
    (gemini_home_link / "roundtrip.txt").write_text("gemini-home-write", encoding="utf-8")
    (codex_cfg_link / "roundtrip.txt").write_text("codex-write", encoding="utf-8")
    (codex_home_link / "roundtrip.txt").write_text("codex-home-write", encoding="utf-8")

    assert (real_home / ".lark-cli" / "roundtrip.txt").read_text(encoding="utf-8") == "lark-write"
    assert (
        real_home / "Library" / "Application Support" / "iTerm2" / "roundtrip.txt"
    ).read_text(encoding="utf-8") == "iterm-write"
    assert (
        real_home / "Library" / "Preferences" / "com.googlecode.iterm2.plist"
    ).read_text(encoding="utf-8") == "prefs-updated"
    assert (real_home / ".config" / "gemini" / "roundtrip.txt").read_text(encoding="utf-8") == "gemini-write"
    assert (real_home / ".gemini" / "roundtrip.txt").read_text(encoding="utf-8") == "gemini-home-write"
    assert (real_home / ".config" / "codex" / "roundtrip.txt").read_text(encoding="utf-8") == "codex-write"
    assert (real_home / ".codex" / "roundtrip.txt").read_text(encoding="utf-8") == "codex-home-write"


def test_seed_user_tool_dirs_skips_missing_sources(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime" / "home"
    real_home.mkdir(parents=True)
    runtime_home.mkdir(parents=True)
    _seed_lark_only_home(real_home)

    _run_seed_helper(real_home, runtime_home)

    assert (runtime_home / ".lark-cli").is_symlink()
    assert not (runtime_home / "Library" / "Application Support" / "iTerm2").exists()
    assert not (runtime_home / "Library" / "Preferences" / "com.googlecode.iterm2.plist").exists()
