"""Round-8 post-merge DX fix: lark-cli wrapper for sandbox HOME.

Problem: lark-cli stores auth tokens in macOS Keychain, keyed on $HOME.
Sandbox seats (`~/.agent-runtime/identities/.../home`) can't see the
operator's user token even though `.lark-cli/` is already symlinked.

Fix: `core/shell-scripts/lark-cli` wrapper — when $AGENT_HOME is set and
differs from $HOME, exec the real binary with $HOME rewritten to
$AGENT_HOME. Seeded into $HOME/bin/lark-cli by
`agent-launcher.sh::seed_user_tool_dirs()` + $HOME/bin prepended to PATH.

These tests pin the wrapper's behavior and the seeding logic.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


_REPO = Path(__file__).resolve().parents[1]
_WRAPPER = _REPO / "core" / "shell-scripts" / "lark-cli"
_LAUNCHER_SANDBOX = _REPO / "core" / "launchers" / "helpers" / "sandbox.sh"


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.is_file(), f"wrapper missing: {_WRAPPER}"
    mode = _WRAPPER.stat().st_mode
    assert mode & 0o111, f"wrapper must be executable (mode={oct(mode)})"


def test_wrapper_bash_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_wrapper_transparently_execs_when_agent_home_equals_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside a sandbox seat: wrapper should be a pure pass-through."""
    fake_cli_dir = tmp_path / "fake-bin"
    fake_cli_dir.mkdir()
    fake_cli = fake_cli_dir / "lark-cli"
    fake_cli.write_text(
        "#!/usr/bin/env bash\n"
        'echo "real-lark-cli invoked with HOME=$HOME args=$*"\n',
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_cli_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "homeish"),
    }
    env.pop("AGENT_HOME", None)  # no sandbox marker → pass-through

    result = subprocess.run(
        [str(_WRAPPER), "auth", "status"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "real-lark-cli invoked" in result.stdout
    assert "auth status" in result.stdout
    # HOME is whatever was exported — wrapper did NOT rewrite it because
    # AGENT_HOME was unset.
    assert str(tmp_path / "homeish") in result.stdout


def test_wrapper_rewrites_home_to_agent_home_in_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside a sandbox seat: wrapper must exec real lark-cli with
    HOME=$AGENT_HOME so Keychain lookup hits the operator's real tokens."""
    fake_cli_dir = tmp_path / "fake-bin"
    fake_cli_dir.mkdir()
    fake_cli = fake_cli_dir / "lark-cli"
    fake_cli.write_text(
        "#!/usr/bin/env bash\n"
        'echo "HOME=$HOME"\n',
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)

    sandbox_home = tmp_path / "sandbox"
    real_home = tmp_path / "real"
    sandbox_home.mkdir()
    real_home.mkdir()

    env = {
        **os.environ,
        "PATH": f"{fake_cli_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(sandbox_home),
        "AGENT_HOME": str(real_home),
    }

    result = subprocess.run(
        [str(_WRAPPER), "auth", "status"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert f"HOME={real_home}" in result.stdout, result.stdout
    assert str(sandbox_home) not in result.stdout, (
        "wrapper leaked sandbox HOME; should have rewritten to AGENT_HOME"
    )


def test_wrapper_errors_cleanly_when_no_real_lark_cli_available(
    tmp_path: Path,
) -> None:
    """If the real lark-cli is not installed, wrapper must fail with
    exit 127 and a diagnostic instead of silently pass-through."""
    # Empty PATH (no lark-cli anywhere) + no fallback locations.
    env = {
        "PATH": str(tmp_path / "empty-dir"),
        "HOME": str(tmp_path),
        # AGENT_HOME unset — pass-through path still needs a real binary.
    }

    # Need to ensure fallbacks /opt/homebrew/bin/lark-cli and
    # /usr/local/bin/lark-cli are NOT present on the test machine, or
    # wrapper will find them. On the CI host this assumption may break;
    # we skip gracefully in that case.
    if any(
        Path(p).exists()
        for p in ("/opt/homebrew/bin/lark-cli", "/usr/local/bin/lark-cli")
    ):
        pytest.skip(
            "real lark-cli present at canonical fallback location; cannot "
            "test 'no binary found' path from this host"
        )

    (tmp_path / "empty-dir").mkdir(exist_ok=True)

    result = subprocess.run(
        [str(_WRAPPER), "auth", "status"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 127, (
        f"expected exit 127, got {result.returncode}: {result.stderr}"
    )
    assert "cannot locate real lark-cli" in result.stderr


def test_wrapper_routes_home_to_project_tool_root_under_per_project(
    tmp_path: Path,
) -> None:
    """Under tools_isolation=per-project the launcher exports
    CLAWSEAT_PROJECT_TOOL_ROOT. The wrapper must prefer it over
    AGENT_HOME so Keychain + config lookups hit the per-project
    namespace, preserving the `project init-tools` / `project
    switch-identity` contract (iter-11, a6d301a finding 1)."""
    fake_cli_dir = tmp_path / "fake-bin"
    fake_cli_dir.mkdir()
    fake_cli = fake_cli_dir / "lark-cli"
    fake_cli.write_text(
        "#!/usr/bin/env bash\n"
        'echo "HOME=$HOME"\n',
        encoding="utf-8",
    )
    fake_cli.chmod(0o755)

    sandbox_home = tmp_path / "sandbox"
    real_home = tmp_path / "real"
    project_root = tmp_path / "real" / ".agent-runtime" / "projects" / "smoke01"
    sandbox_home.mkdir()
    real_home.mkdir()
    project_root.mkdir(parents=True)

    env = {
        **os.environ,
        "PATH": f"{fake_cli_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(sandbox_home),
        "AGENT_HOME": str(real_home),
        "CLAWSEAT_PROJECT_TOOL_ROOT": str(project_root),
    }

    result = subprocess.run(
        [str(_WRAPPER), "auth", "status"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert f"HOME={project_root}" in result.stdout, result.stdout
    # Neither sandbox HOME nor operator AGENT_HOME should have leaked in.
    assert str(sandbox_home) not in result.stdout, result.stdout
    # Be precise: match exactly the AGENT_HOME string, not a substring of
    # project_root (which is under AGENT_HOME in this fixture).
    assert f"HOME={real_home}\n" not in result.stdout, (
        "per-project tool root must take priority over AGENT_HOME"
    )


def test_wrapper_does_not_loop_when_reachable_via_multiple_symlinks(
    tmp_path: Path,
) -> None:
    """If the wrapper is reachable through more than one symlink alias
    on PATH, `_resolve_real_lark_cli` must NOT accept any alias as the
    real binary — canonical-path comparison is what prevents recursion
    (iter-11, a6d301a finding 2). Regression pins the behavior: with
    only wrapper aliases (and no real binary fallback), wrapper must
    exit 127 cleanly rather than exec-loop until a timeout."""
    # Skip cleanly on hosts where a real lark-cli binary exists at
    # canonical fallback paths — the test relies on being able to
    # observe the "cannot locate real lark-cli" exit, which only fires
    # when no fallback is installed.
    if any(
        Path(p).exists()
        for p in ("/opt/homebrew/bin/lark-cli", "/usr/local/bin/lark-cli")
    ):
        pytest.skip(
            "real lark-cli present at canonical fallback location; cannot "
            "verify loop-prevention in isolation from this host"
        )

    # Two separate dirs on PATH, each holding a symlink named
    # `lark-cli` → canonical wrapper. Pre-iter-11 code would accept
    # the second alias (BASH_SOURCE[0] != canonical target) and exec
    # back into the wrapper, looping until the subprocess timed out.
    alias_dir_a = tmp_path / "alias-a"
    alias_dir_b = tmp_path / "alias-b"
    alias_dir_a.mkdir()
    alias_dir_b.mkdir()
    (alias_dir_a / "lark-cli").symlink_to(_WRAPPER)
    (alias_dir_b / "lark-cli").symlink_to(_WRAPPER)

    # Invoke via alias_dir_a's symlink so BASH_SOURCE[0] is the
    # symlink path, not the canonical wrapper.
    invocation = alias_dir_a / "lark-cli"

    env = {
        "PATH": f"{alias_dir_a}{os.pathsep}{alias_dir_b}",
        "HOME": str(tmp_path / "homeish"),
        # AGENT_HOME unset — exercising the pass-through resolve path,
        # which is where the loop was observed.
    }

    try:
        result = subprocess.run(
            [str(invocation), "auth", "status"],
            capture_output=True,
            text=True,
            env=env,
            timeout=5,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"wrapper exec-looped under multiple symlink aliases: {exc}"
        )

    assert result.returncode == 127, (
        f"expected exit 127 (no real binary), got {result.returncode}: "
        f"{result.stderr}"
    )
    assert "cannot locate real lark-cli" in result.stderr


def test_launcher_seed_user_tool_dirs_references_wrapper() -> None:
    """Regression guard: helpers/sandbox.sh::seed_user_tool_dirs must
    symlink the wrapper into $runtime_home/bin/lark-cli and prepend
    that bin dir to PATH. We check by text since we don't run the
    launcher end-to-end in this test."""
    launcher_text = _LAUNCHER_SANDBOX.read_text(encoding="utf-8")
    assert "core/shell-scripts/lark-cli" in launcher_text, (
        "launcher must reference the wrapper source path"
    )
    assert "$runtime_home/bin/lark-cli" in launcher_text, (
        "launcher must symlink wrapper into $runtime_home/bin/lark-cli"
    )
    # PATH prepend (allow either form: $runtime_home/bin or "$runtime_home/bin").
    assert '"$runtime_home/bin' in launcher_text or \
        "$runtime_home/bin" in launcher_text, (
        "launcher must prepend $runtime_home/bin to PATH"
    )
    assert 'export PATH="$runtime_home/bin' in launcher_text, (
        "launcher must export the new PATH (not just set it locally)"
    )
