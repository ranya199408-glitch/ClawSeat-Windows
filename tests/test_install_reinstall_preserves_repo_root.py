from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_reinstall_preserves_existing_repo_root_without_force_repo_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_dir = home / ".agents" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "project.toml").write_text(
        'name = "demo"\nrepo_root = "/foo/bar"\n',
        encoding="utf-8",
    )

    probe = f"""
set -euo pipefail
source "{_REPO / 'scripts' / 'install.sh'}"
PROJECT=demo
compute_project_paths
PROJECT_REPO_ROOT="/new/root"
FORCE_REPO_ROOT=""
DRY_RUN=0
_reinstall_project
[[ "$PROJECT_REPO_ROOT" == "/foo/bar" ]]
_clear_reinstall_backups
"""
    result = subprocess.run(
        ["bash", "-c", probe],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHON_BIN": sys.executable,
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
