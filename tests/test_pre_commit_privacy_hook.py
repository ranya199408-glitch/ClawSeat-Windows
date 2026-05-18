from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

_SETUP_HELPERS = Path(__file__).with_name("test_install_privacy_setup.py")
_setup_spec = importlib.util.spec_from_file_location("_h3_install_privacy_setup", _SETUP_HELPERS)
assert _setup_spec is not None
assert _setup_spec.loader is not None
_setup = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(_setup)

_prepare_h3_fake_root = _setup._prepare_h3_fake_root
_run_install = _setup._run_install
_write_executable = _setup._write_executable


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _mock_privacy_check(root: Path, log: Path) -> None:
    _write_executable(
        root / "core" / "scripts" / "privacy-check.sh",
        f"#!/usr/bin/env bash\nprintf 'privacy\\n' >> {str(log)!r}\nexit 0\n",
    )


def test_pre_commit_hook_installation_is_idempotent(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    repo = _git_repo(tmp_path)
    first = _run_install(root, home, py_stubs, project="h3hooka", repo_root=repo)
    second = _run_install(root, home, py_stubs, project="h3hooka", repo_root=repo)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    hook = repo / ".git" / "hooks" / "pre-commit"
    text = hook.read_text(encoding="utf-8")
    assert text.count("CLAWSEAT_PRIVACY_CHECK_BEGIN") == 1
    assert "privacy-check.sh" in text


def test_pre_commit_hook_invokes_privacy_check(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    repo = _git_repo(tmp_path)
    privacy_log = tmp_path / "privacy.log"
    _mock_privacy_check(root, privacy_log)
    result = _run_install(root, home, py_stubs, project="h3hookb", repo_root=repo)
    assert result.returncode == 0, result.stderr

    hook = repo / ".git" / "hooks" / "pre-commit"
    run = subprocess.run([str(hook)], cwd=repo, text=True, capture_output=True, check=False)
    assert run.returncode == 0, run.stderr
    assert privacy_log.read_text(encoding="utf-8") == "privacy\n"


def test_pre_commit_hook_preserves_existing_hook(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    repo = _git_repo(tmp_path)
    privacy_log = tmp_path / "privacy.log"
    local_log = tmp_path / "local.log"
    _mock_privacy_check(root, privacy_log)

    existing = repo / ".git" / "hooks" / "pre-commit"
    _write_executable(
        existing,
        f"#!/usr/bin/env bash\nprintf 'local\\n' >> {str(local_log)!r}\nexit 0\n",
    )

    result = _run_install(root, home, py_stubs, project="h3hookc", repo_root=repo)
    assert result.returncode == 0, result.stderr
    preserved = repo / ".git" / "hooks" / "pre-commit.clawseat-local"
    assert preserved.is_file()

    hook = repo / ".git" / "hooks" / "pre-commit"
    run = subprocess.run([str(hook)], cwd=repo, text=True, capture_output=True, check=False)
    assert run.returncode == 0, run.stderr
    assert privacy_log.read_text(encoding="utf-8") == "privacy\n"
    assert local_log.read_text(encoding="utf-8") == "local\n"
