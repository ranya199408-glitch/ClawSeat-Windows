from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_PREFLIGHT = _REPO / "scripts" / "install" / "lib" / "preflight.sh"
_INSTALL = _REPO / "scripts" / "install.sh"


def _run(cmd: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True)


def _init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "clawseat-main"
    root.mkdir()
    _run(["git", "init", "-b", "main"], cwd=root)
    _run(["git", "config", "user.email", "test@example.com"], cwd=root)
    _run(["git", "config", "user.name", "Test User"], cwd=root)
    (root / "README.md").write_text("main\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=root)
    _run(["git", "commit", "-m", "initial"], cwd=root)
    return root


def _select_root(candidate: Path) -> subprocess.CompletedProcess[str]:
    script = f"""
set -euo pipefail
warn() {{ printf 'WARN: %s\\n' "$*" >&2; }}
source "{_PREFLIGHT}"
_select_fresh_clawseat_root "$1"
"""
    return subprocess.run(
        ["bash", "-c", script, "selector", str(candidate)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_install_skips_detached_head_worktree(tmp_path: Path) -> None:
    """install repo-root selection skips a detached-HEAD worktree and warns."""
    main_root = _init_repo(tmp_path)
    detached_root = tmp_path / "clawseat-detached"
    _run(["git", "worktree", "add", "--detach", str(detached_root), "HEAD"], cwd=main_root)

    result = _select_root(detached_root)

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == main_root.resolve()
    assert "detached" in result.stderr
    assert "Skipping" in result.stderr
    assert "--force-repo-root" in result.stderr


def test_install_prefers_main_branch_worktree(tmp_path: Path) -> None:
    """install repo-root selection selects main over a newer feature branch."""
    main_root = _init_repo(tmp_path)
    feature_root = tmp_path / "clawseat-feature"
    _run(["git", "worktree", "add", "-b", "feature", str(feature_root), "main"], cwd=main_root)
    (feature_root / "README.md").write_text("feature\n", encoding="utf-8")
    _run(["git", "commit", "-am", "feature change"], cwd=feature_root)

    result = _select_root(feature_root)

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).resolve() == main_root.resolve()


def test_force_repo_root_bypasses_autoselection(tmp_path: Path) -> None:
    forced_root = _REPO
    home = tmp_path / "home"
    result = subprocess.run(
        [
            "bash",
            str(_INSTALL),
            "--dry-run",
            "--project",
            "vforce",
            "--force-repo-root",
            str(forced_root),
        ],
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHON_BIN": sys.executable,
            "CLAWSEAT_QA_PATROL_CRON_OPT_IN": "n",
        },
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"REPO_ROOT forced to {forced_root}" in result.stderr
    assert f"{forced_root}/core/preflight.py" in result.stdout
