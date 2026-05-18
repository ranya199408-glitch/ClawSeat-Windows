from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "core" / "launchers" / "agent-launcher.sh"


def _seed_project_root(project_root: Path) -> None:
    (project_root / ".lark-cli").mkdir(parents=True, exist_ok=True)
    (project_root / ".lark-cli" / "config.json").write_text("project-lark", encoding="utf-8")
    (project_root / "Library" / "Application Support" / "iTerm2").mkdir(parents=True, exist_ok=True)
    (project_root / "Library" / "Application Support" / "iTerm2" / "state.txt").write_text(
        "iterm-state",
        encoding="utf-8",
    )
    (project_root / "Library" / "Preferences").mkdir(parents=True, exist_ok=True)
    (project_root / "Library" / "Preferences" / "com.googlecode.iterm2.plist").write_text(
        "prefs",
        encoding="utf-8",
    )
    (project_root / ".config" / "gemini").mkdir(parents=True, exist_ok=True)
    (project_root / ".config" / "gemini" / "settings.json").write_text(
        "gemini-settings",
        encoding="utf-8",
    )
    (project_root / ".gemini").mkdir(parents=True, exist_ok=True)
    (project_root / ".gemini" / "auth.json").write_text("gemini-auth", encoding="utf-8")
    (project_root / ".config" / "codex").mkdir(parents=True, exist_ok=True)
    (project_root / ".config" / "codex" / "config.toml").write_text("model = 'gpt-5.4'", encoding="utf-8")
    (project_root / ".codex").mkdir(parents=True, exist_ok=True)
    (project_root / ".codex" / "auth.json").write_text("codex-auth", encoding="utf-8")


def _run_seed_helper(runtime_home: Path, project_name: str, project_root: Path) -> None:
    env = {
        **os.environ,
        "HOME": str(runtime_home.parent.parent),
        "CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY": "1",
        "CLAWSEAT_PROJECT": project_name,
        "CLAWSEAT_TOOLS_ISOLATION": "per-project",
        "CLAWSEAT_PROJECT_TOOL_ROOT": str(project_root),
    }
    snippet = "\n".join(
        [
            "set -euo pipefail",
            f"source {shlex.quote(str(LAUNCHER))}",
            f"seed_user_tool_dirs {shlex.quote(str(runtime_home))} {shlex.quote(project_name)}",
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


def test_seed_user_tool_dirs_prefers_project_root_when_explicitly_isolated(tmp_path: Path) -> None:
    runtime_home = tmp_path / "runtime" / "home"
    project_root = tmp_path / "real_home" / ".agent-runtime" / "projects" / "smoke01"
    runtime_home.mkdir(parents=True)
    project_root.mkdir(parents=True)
    _seed_project_root(project_root)

    _run_seed_helper(runtime_home, "smoke01", project_root)

    for subpath, source_subpath in (
        (".lark-cli", ".lark-cli"),
        (".gemini", ".gemini"),
        (".codex", ".codex"),
        ("Library/Application Support/iTerm2", "Library/Application Support/iTerm2"),
        ("Library/Preferences/com.googlecode.iterm2.plist", "Library/Preferences/com.googlecode.iterm2.plist"),
    ):
        link = runtime_home / subpath
        assert link.is_symlink()
        assert link.readlink() == project_root / source_subpath

    (runtime_home / ".lark-cli" / "roundtrip.txt").write_text("lark-write", encoding="utf-8")
    assert (project_root / ".lark-cli" / "roundtrip.txt").read_text(encoding="utf-8") == "lark-write"


# ── wrapper-seed branch coverage (iter-14, reviewer 3b0ce9e nit) ─────────


def _run_seed_helper_without_root(
    runtime_home: Path, project_name: str, project_root: Path
) -> None:
    """Variant of `_run_seed_helper` that genuinely exercises the
    CLAWSEAT_ROOT-unset branch. Defense in depth against three
    injection vectors the reviewer identified:

    1. Ambient shell exports — scrubbed from the subprocess env dict.
    2. Non-interactive-bash `BASH_ENV` auto-source — scrubbed from the
       subprocess env dict (bash honors it before running `-c`).
    3. POSIX-sh `ENV` equivalent — scrubbed for the same reason.

    Also adds a defensive `unset CLAWSEAT_ROOT` to the snippet itself,
    which runs AFTER any startup file processing and before `source`,
    so even exotic shell configs (custom /etc/bash.bashrc chains,
    etc.) can't reintroduce the var via a path we haven't thought of."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"CLAWSEAT_ROOT", "BASH_ENV", "ENV"}
    }
    env.update(
        {
            "HOME": str(runtime_home.parent.parent),
            "CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY": "1",
            "CLAWSEAT_PROJECT": project_name,
            "CLAWSEAT_TOOLS_ISOLATION": "per-project",
            "CLAWSEAT_PROJECT_TOOL_ROOT": str(project_root),
        }
    )
    snippet = "\n".join(
        [
            "set -euo pipefail",
            # Belt + suspenders: strip CLAWSEAT_ROOT even if a startup
            # file re-exported it after we scrubbed the env dict.
            "unset CLAWSEAT_ROOT",
            f"source {shlex.quote(str(LAUNCHER))}",
            f"seed_user_tool_dirs {shlex.quote(str(runtime_home))} {shlex.quote(project_name)}",
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


def test_seed_user_tool_dirs_wrapper_block_noops_when_clawseat_root_unset(
    tmp_path: Path,
) -> None:
    """With CLAWSEAT_ROOT unset (e.g. test/library callers under set -u),
    the wrapper-seed block must no-op cleanly: no `$runtime_home/bin/lark-cli`
    is created and the primary seed loop completes. Pins the gate added
    in iter-13 3b0ce9e. Runs with CLAWSEAT_ROOT actively scrubbed from
    the subprocess env so ambient shell exports (e.g. reviewer's shell
    where CLAWSEAT_ROOT=/tmp/fake-home't mask the test."""
    runtime_home = tmp_path / "runtime" / "home"
    project_root = tmp_path / "real_home" / ".agent-runtime" / "projects" / "smoke01"
    runtime_home.mkdir(parents=True)
    project_root.mkdir(parents=True)
    _seed_project_root(project_root)

    _run_seed_helper_without_root(runtime_home, "smoke01", project_root)

    # Primary seed loop succeeded → .lark-cli symlink exists (from primary
    # loop, not from wrapper-seed).
    assert (runtime_home / ".lark-cli").is_symlink()
    # Wrapper-seed block must have been skipped entirely.
    wrapper_tgt = runtime_home / "bin" / "lark-cli"
    assert not wrapper_tgt.exists() and not wrapper_tgt.is_symlink(), (
        f"wrapper-seed leaked under unset CLAWSEAT_ROOT: {wrapper_tgt}"
    )


def _run_seed_helper_with_root(
    runtime_home: Path,
    project_name: str,
    project_root: Path,
    clawseat_root: Path,
) -> subprocess.CompletedProcess[str]:
    """Mirror of `_run_seed_helper_without_root` for the set-CLAWSEAT_ROOT
    case: strip BASH_ENV/ENV from env AND re-export the target value in
    the bash snippet so any startup-file injection is overridden."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"CLAWSEAT_ROOT", "BASH_ENV", "ENV"}
    }
    env.update(
        {
            "HOME": str(runtime_home.parent.parent),
            "CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY": "1",
            "CLAWSEAT_PROJECT": project_name,
            "CLAWSEAT_TOOLS_ISOLATION": "per-project",
            "CLAWSEAT_PROJECT_TOOL_ROOT": str(project_root),
        }
    )
    # Quote the CLAWSEAT_ROOT path for the bash literal.
    quoted_root = shlex.quote(str(clawseat_root))
    snippet = "\n".join(
        [
            "set -euo pipefail",
            # Belt + suspenders: re-export to the test's intended value
            # AFTER any BASH_ENV / startup file has run.
            f"export CLAWSEAT_ROOT={quoted_root}",
            f"source {shlex.quote(str(LAUNCHER))}",
            f"seed_user_tool_dirs {shlex.quote(str(runtime_home))} {shlex.quote(project_name)}",
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
    return result


def test_seed_user_tool_dirs_backs_up_existing_bin_lark_cli(tmp_path: Path) -> None:
    """When `$runtime_home/bin/lark-cli` already exists (and is not our
    wrapper symlink), the wrapper-seed block must archive it under
    `.sandbox-pre-seed-backup/bin/lark-cli.<timestamp>` and replace with
    a symlink to the canonical wrapper. Pins the replace/backup branch
    at core/launchers/agent-launcher.sh:462-466."""
    runtime_home = tmp_path / "runtime" / "home"
    project_root = tmp_path / "real_home" / ".agent-runtime" / "projects" / "smoke01"
    runtime_home.mkdir(parents=True)
    project_root.mkdir(parents=True)
    _seed_project_root(project_root)

    # Pre-existing non-symlink at wrapper target — must be backed up.
    bin_dir = runtime_home / "bin"
    bin_dir.mkdir(parents=True)
    existing = bin_dir / "lark-cli"
    existing.write_text("#!/bin/sh\necho legacy-tenant\n", encoding="utf-8")
    existing.chmod(0o755)

    wrapper_src = REPO_ROOT / "core" / "shell-scripts" / "lark-cli"
    assert wrapper_src.is_file(), f"test fixture missing: {wrapper_src}"

    _run_seed_helper_with_root(runtime_home, "smoke01", project_root, REPO_ROOT)

    # Target is now a symlink pointing at the canonical wrapper.
    assert existing.is_symlink(), f"wrapper-seed didn't replace: {existing}"
    assert existing.readlink() == wrapper_src, (
        f"wrapper-seed pointed at wrong target: {existing.readlink()}"
    )

    # Legacy payload archived under .sandbox-pre-seed-backup/bin/lark-cli.*
    backup_dir = runtime_home / ".sandbox-pre-seed-backup" / "bin"
    assert backup_dir.is_dir(), f"backup dir missing: {backup_dir}"
    backups = sorted(backup_dir.glob("lark-cli.*"))
    assert backups, f"no lark-cli backup found under {backup_dir}"
    # Legacy payload preserved byte-identical.
    assert "legacy-tenant" in backups[0].read_text(encoding="utf-8")

