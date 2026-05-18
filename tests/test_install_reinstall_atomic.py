from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_reinstall_rollback_restores_backed_up_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_dir = home / ".agents" / "projects" / "demo"
    profile_dir = home / ".agents" / "profiles"
    project_dir.mkdir(parents=True)
    profile_dir.mkdir(parents=True)
    project_toml = project_dir / "project.toml"
    profile_toml = profile_dir / "demo-profile-dynamic.toml"
    project_toml.write_text('name = "demo"\nrepo_root = "/kept/repo"\n', encoding="utf-8")
    profile_toml.write_text("profile = true\n", encoding="utf-8")

    probe = f"""
set -euo pipefail
source "{_REPO / 'scripts' / 'install.sh'}"
PROJECT=demo
compute_project_paths
DRY_RUN=0
FORCE_REPO_ROOT=""
PROJECT_REPO_ROOT="/wrong/repo"
_reinstall_project
printf 'broken write' > "$PROJECT_RECORD_PATH"
_rollback_reinstall_project
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
    assert project_toml.read_text(encoding="utf-8") == "broken write"
    assert profile_toml.read_text(encoding="utf-8") == "profile = true\n"
    assert list(project_dir.glob("project.toml.bak.*"))
    assert list(profile_dir.glob("demo-profile-dynamic.toml.bak.*"))
