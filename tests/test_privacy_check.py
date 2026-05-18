from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "scripts" / "privacy-check.sh"


def _run(repo: Path, home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=repo,
        env={**os.environ, "HOME": str(home)},
        text=True,
        capture_output=True,
        check=False,
    )


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _privacy_file(home: Path, text: str) -> Path:
    path = home / ".agents" / "memory" / "machine" / "privacy.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _stage(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True, capture_output=True)


def test_privacy_check_missing_file_warns_and_passes(tmp_path: Path) -> None:
    result = _run(_git_repo(tmp_path), tmp_path / "home")
    assert result.returncode == 0
    assert "privacy KB missing" in result.stderr


def test_privacy_check_no_block_lines_passes(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    _privacy_file(home, "# Privacy KB\n# no blocks\n")
    _stage(repo, "safe.txt", "<API_KEY> is present but no BLOCK lines exist\n")
    assert _run(repo, home).returncode == 0


def test_privacy_check_blocks_staged_secret_pattern(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    _privacy_file(home, "BLOCK: sk-\n")
    _stage(repo, "secret.txt", "token = <API_KEY>\n")
    result = _run(repo, home)
    assert result.returncode == 1
    assert "sk-" in result.stderr
    assert "secret.txt" in result.stderr


def test_privacy_check_allows_staged_diff_without_pattern(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    _privacy_file(home, "BLOCK: sk-\n")
    _stage(repo, "safe.txt", "token = public\n")
    assert _run(repo, home).returncode == 0


def test_privacy_check_reports_multiple_block_patterns(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    _privacy_file(home, "BLOCK: sk-\nBLOCK: ghp_\n")
    _stage(repo, "tokens.txt", "a = <API_KEY>\nb = ghp_test\n")
    result = _run(repo, home)
    assert result.returncode == 1
    assert "sk-" in result.stderr
    assert "ghp_" in result.stderr


def test_privacy_check_empty_staged_diff_passes(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    _privacy_file(home, "BLOCK: sk-\n")
    assert _run(repo, home).returncode == 0


def test_privacy_check_unreadable_file_warns_and_passes(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    privacy = _privacy_file(home, "BLOCK: sk-\n")
    privacy.chmod(0)
    try:
      result = _run(repo, home)
    finally:
      privacy.chmod(stat.S_IRUSR | stat.S_IWUSR)
    assert result.returncode == 0
    assert "not readable" in result.stderr or result.stderr == ""


def test_privacy_check_invalid_regex_falls_back_to_literal(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "home"
    _privacy_file(home, "BLOCK: [abc\n")
    _stage(repo, "literal.txt", "contains [abc exactly\n")
    result = _run(repo, home)
    assert result.returncode == 1
    assert "[abc" in result.stderr
