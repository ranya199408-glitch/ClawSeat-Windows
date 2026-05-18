from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"
INSTALL = REPO / "scripts" / "install.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "checkout", "-b", "main")
    (repo / "README.md").write_text("# temp\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _branch_state(repo: Path, home: Path) -> dict[str, object]:
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_ROOT": str(repo),
    }
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_branch_state"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_detect_branch_state_warns_off_main(tmp_path: Path) -> None:
    """Branch detection marks non-main checkouts as warning state."""
    home = tmp_path / "home"
    home.mkdir()
    repo = _make_repo(tmp_path)

    assert _branch_state(repo, home) == {"branch": "main", "warn": False}

    _git(repo, "checkout", "-b", "feature/install")
    assert _branch_state(repo, home) == {"branch": "feature/install", "warn": True}


def test_install_detect_only_outputs_detect_all_json(tmp_path: Path) -> None:
    """--detect-only exposes the same summary JSON through install.sh."""
    home = tmp_path / "home"
    home.mkdir()
    repo = _make_repo(tmp_path)
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "PYTHON_BIN": sys.executable,
    }
    result = subprocess.run(
        [
            "bash",
            str(INSTALL),
            "--detect-only",
            "--force-repo-root",
            str(repo),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == {"oauth", "pty", "branch", "existing_projects", "timestamp"}
    assert data["branch"] == {"branch": "main", "warn": False}
    assert data["existing_projects"] == []
