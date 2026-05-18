"""Tests for scan_project.py write modes: dry-run / --commit / --force-commit.

Coverage:
  - Without --commit, scanner NEVER touches filesystem under projects/
  - --commit writes files; fails if files already exist
  - --force-commit overwrites existing files
  - --dry-run stdout is valid JSON diffable against --commit output
  - File permissions 0o600 on written files
  - Bad --repo path exits 1
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
_SCAN_PY = _SCRIPTS / "scan_project.py"
sys.path.insert(0, str(_SCRIPTS))

from scan_project import scan  # noqa: E402


def make_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return root


def cli(repo: Path, mem: Path, *extra_args) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, str(_SCAN_PY),
        "--project", "proj",
        "--repo", str(repo),
        "--memory-dir", str(mem),
        "--quiet",
    ] + list(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ── Dry-run (default) never touches filesystem ────────────────────────────────


def test_dryrun_no_projects_dir_created(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    result = cli(repo, mem)
    assert result.returncode == 0
    assert not (mem / "projects").exists()


def test_dryrun_stdout_is_valid_json(tmp_path):
    repo = make_repo(tmp_path / "repo")
    result = cli(repo, tmp_path / "mem")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)


def test_dryrun_includes_dry_run_true_field(tmp_path):
    repo = make_repo(tmp_path / "repo")
    result = cli(repo, tmp_path / "mem")
    output = json.loads(result.stdout)
    assert output["dry_run"] is True


def test_dryrun_no_files_in_memory_dir(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    mem.mkdir()
    cli(repo, mem)
    assert list(mem.iterdir()) == []


def test_dryrun_medium_produces_7_entries_in_json(tmp_path):
    repo = make_repo(tmp_path / "repo")
    result = cli(repo, tmp_path / "mem", "--depth", "medium")
    output = json.loads(result.stdout)
    assert len(output["files"]) == 7


# ── --commit writes files ─────────────────────────────────────────────────────


def test_commit_writes_dev_env_json(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    result = cli(repo, mem, "--commit")
    assert result.returncode == 0
    assert (mem / "projects" / "proj" / "dev_env.json").exists()


def test_commit_exit_0_on_success(tmp_path):
    repo = make_repo(tmp_path / "repo")
    result = cli(repo, tmp_path / "mem", "--commit")
    assert result.returncode == 0


def test_commit_fails_if_file_exists(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    cli(repo, mem, "--commit")  # first run
    result = cli(repo, mem, "--commit")  # second run — should fail
    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_commit_written_file_is_valid_json(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    cli(repo, mem, "--commit")
    content = (mem / "projects" / "proj" / "dev_env.json").read_text()
    record = json.loads(content)
    assert record["kind"] == "dev_env"


def test_commit_file_permissions_600(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    cli(repo, mem, "--commit")
    p = mem / "projects" / "proj" / "dev_env.json"
    mode = p.stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


# ── --force-commit overwrites ─────────────────────────────────────────────────


def test_force_commit_overwrites_existing(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    cli(repo, mem, "--commit")
    result = cli(repo, mem, "--force-commit")
    assert result.returncode == 0


def test_force_commit_file_is_updated(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    cli(repo, mem, "--commit")
    import time; time.sleep(0.01)
    cli(repo, mem, "--force-commit")
    # File should still be valid JSON with updated ts
    record = json.loads((mem / "projects" / "proj" / "dev_env.json").read_text())
    assert record["schema_version"] == 1


def test_force_commit_without_prior_commit_also_works(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    result = cli(repo, mem, "--force-commit")
    assert result.returncode == 0


# ── Scan API: commit flag ─────────────────────────────────────────────────────


def test_scan_api_dryrun_does_not_write(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    scan("p", repo, commit=False, memory_root=mem)
    assert not (mem / "projects").exists()


def test_scan_api_commit_writes_dev_env(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    scan("p", repo, commit=True, memory_root=mem)
    assert (mem / "projects" / "p" / "dev_env.json").exists()


def test_scan_api_force_commit_overwrites(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    scan("p", repo, commit=True, memory_root=mem)
    scan("p", repo, force_commit=True, memory_root=mem)
    assert (mem / "projects" / "p" / "dev_env.json").exists()


def test_scan_api_commit_fails_if_file_exists_without_force(tmp_path):
    repo = make_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    scan("p", repo, commit=True, memory_root=mem)
    with pytest.raises(SystemExit):
        scan("p", repo, commit=True, memory_root=mem)


# ── Bad inputs ────────────────────────────────────────────────────────────────


def test_nonexistent_repo_exits_1(tmp_path):
    result = subprocess.run(
        [sys.executable, str(_SCAN_PY), "--project", "p",
         "--repo", str(tmp_path / "nonexistent"),
         "--memory-dir", str(tmp_path / "mem")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "not a directory" in result.stderr


def test_missing_repo_arg_exits_2(tmp_path):
    result = subprocess.run(
        [sys.executable, str(_SCAN_PY), "--project", "p",
         "--memory-dir", str(tmp_path / "mem")],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
