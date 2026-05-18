from __future__ import annotations

import importlib.util
import os
import plistlib
import stat
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_UPDATE_SCRIPT = _REPO / "scripts" / "clawseat-update.sh"
_INSTALLER = _REPO / "scripts" / "install_clawseat_autoupdate.py"


def _run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True, **kwargs)


def _git(cmd: list[str], cwd: Path) -> str:
    return _run(["git", *cmd], cwd=cwd).stdout.strip()


def _make_repo_pair(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _run(["git", "init", "--bare", str(remote)], cwd=tmp_path)
    _run(["git", "init", "-b", "main", str(repo)], cwd=tmp_path)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test User"], repo)
    (repo / "README.md").write_text("one\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "initial"], repo)
    _git(["remote", "add", "clawseat", str(remote)], repo)
    _git(["push", "-u", "clawseat", "main"], repo)
    return repo, remote


def _advance_remote(tmp_path: Path, remote: Path) -> str:
    upstream = tmp_path / "upstream"
    _run(["git", "clone", str(remote), str(upstream)], cwd=tmp_path)
    _git(["switch", "main"], upstream)
    _git(["config", "user.email", "test@example.com"], upstream)
    _git(["config", "user.name", "Test User"], upstream)
    (upstream / "README.md").write_text("two\n", encoding="utf-8")
    _git(["commit", "-am", "advance"], upstream)
    _git(["push", "origin", "main"], upstream)
    return _git(["rev-parse", "HEAD"], upstream)


def _update_env(tmp_path: Path, repo: Path) -> dict[str, str]:
    return {
        **os.environ,
        "CLAWSEAT_UPDATE_REPO": str(repo),
        "CLAWSEAT_AUTO_UPDATE_LOG": str(tmp_path / "auto-update.log"),
    }


def test_update_skip_non_main_branch(tmp_path: Path) -> None:
    repo, remote = _make_repo_pair(tmp_path)
    _advance_remote(tmp_path, remote)
    _git(["switch", "-c", "dev"], repo)
    before = _git(["rev-parse", "HEAD"], repo)

    subprocess.run(["bash", str(_UPDATE_SCRIPT)], check=True, env=_update_env(tmp_path, repo))

    assert _git(["rev-parse", "HEAD"], repo) == before
    assert "skip: on dev" in (tmp_path / "auto-update.log").read_text(encoding="utf-8")


def test_update_skip_dirty_tree(tmp_path: Path) -> None:
    repo, remote = _make_repo_pair(tmp_path)
    _advance_remote(tmp_path, remote)
    before = _git(["rev-parse", "HEAD"], repo)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    subprocess.run(["bash", str(_UPDATE_SCRIPT)], check=True, env=_update_env(tmp_path, repo))

    assert _git(["rev-parse", "HEAD"], repo) == before
    assert "skip: dirty tree" in (tmp_path / "auto-update.log").read_text(encoding="utf-8")


def test_update_fast_forward(tmp_path: Path) -> None:
    repo, remote = _make_repo_pair(tmp_path)
    remote_sha = _advance_remote(tmp_path, remote)

    subprocess.run(["bash", str(_UPDATE_SCRIPT)], check=True, env=_update_env(tmp_path, repo))

    assert _git(["rev-parse", "HEAD"], repo) == remote_sha
    assert "updated " in (tmp_path / "auto-update.log").read_text(encoding="utf-8")


def _load_installer():
    spec = importlib.util.spec_from_file_location("install_clawseat_autoupdate", _INSTALLER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_install_clawseat_autoupdate_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    installer = _load_installer()
    repo = tmp_path / "ClawSeat"
    update_script = repo / "scripts" / "clawseat-update.sh"
    update_script.parent.mkdir(parents=True)
    update_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    update_script.chmod(update_script.stat().st_mode | stat.S_IXUSR)
    calls: list[list[str]] = []

    def fake_runner(argv):
        calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0)

    first = installer.install(repo, runner=fake_runner)
    second = installer.install(repo, runner=fake_runner)
    payload = plistlib.loads(first.read_bytes())

    assert first == second
    assert payload["ProgramArguments"] == ["/bin/bash", str(update_script)]
    assert payload["StartCalendarInterval"] == {"Hour": 3, "Minute": 0}
    assert payload["RunAtLoad"] is False
    assert payload["StandardOutPath"] == str(tmp_path / ".clawseat" / "auto-update.log")
    assert payload["StandardErrorPath"] == str(tmp_path / ".clawseat" / "auto-update.log")
    assert [call[1] for call in calls].count("bootstrap") == 2

    installer.uninstall(runner=fake_runner)
    assert not first.exists()
