from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_complete_handoff import _dispatch, _write_profile


ROOT = Path(__file__).resolve().parents[1]
COMPLETE_SCRIPT = ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "complete_handoff.py"


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    return repo


def _commit(repo: Path, path: str, contents: str, message: str) -> str:
    file_path = repo / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", path], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message], check=True)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _update_clawseat_main(repo: Path, commit_sha: str) -> None:
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/clawseat/main", commit_sha], check=True)


def _fake_gh_env(tmp_path: Path, files: list[str]) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_path = bin_dir / "gh"
    gh_path.write_text(
        """#!/usr/bin/env python3
import os
import sys

if len(sys.argv) >= 3 and sys.argv[1] == "pr" and sys.argv[2] == "view":
    print(os.environ["GH_FILES_JSON"])
    raise SystemExit(0)

print("unsupported gh invocation", file=sys.stderr)
raise SystemExit(1)
""",
        encoding="utf-8",
    )
    gh_path.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["GH_FILES_JSON"] = json.dumps({"files": [{"path": file_path} for file_path in files]})
    return env


def _run_complete(
    profile: Path,
    *,
    env: dict[str, str],
    base_drift_acknowledged: bool = False,
    drift_reason: str | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(COMPLETE_SCRIPT),
        "--profile",
        str(profile),
        "--source",
        "builder",
        "--target",
        "planner",
        "--task-id",
        "task-1",
        "--title",
        "task-1",
        "--summary",
        "done",
        "--user-summary",
        "done",
        "--branch",
        "feature",
        "--pr-number",
        "1",
        "--ci-conclusion",
        "SUCCESS",
        "--no-notify",
    ]
    if base_drift_acknowledged:
        cmd.append("--base-drift-acknowledged")
    if drift_reason is not None:
        cmd.extend(["--drift-reason", drift_reason])
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _prepare_repo(tmp_path: Path, *, feature_file: str, main_file: str) -> tuple[Path, Path, str, str]:
    repo = _init_repo(tmp_path)
    base_sha = _commit(repo, "base.txt", "base\n", "base")
    _update_clawseat_main(repo, base_sha)

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature"], check=True)
    _commit(repo, feature_file, "feature\n", "feature")
    profile, _handoffs, _tasks = _write_profile(tmp_path, repo)

    first = _dispatch(
        profile,
        "task-1",
        expected_branch="feature",
        expected_worktree="/tmp/feature-wt",
    )
    assert first.returncode == 0

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "main"], check=True)
    main_sha = _commit(repo, main_file, "main\n", "main drift")
    _update_clawseat_main(repo, main_sha)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "feature"], check=True)
    return repo, profile, base_sha, main_sha


def test_completion_rejects_unacknowledged_base_drift(tmp_path: Path) -> None:
    _repo, profile, _base_sha, _main_sha = _prepare_repo(
        tmp_path, feature_file="feature.txt", main_file="main-only.txt"
    )
    result = _run_complete(profile, env=os.environ.copy())
    assert result.returncode != 0
    assert "base drift detected" in result.stderr


def test_completion_accepts_acknowledged_orthogonal_base_drift(tmp_path: Path) -> None:
    _repo, profile, base_sha, main_sha = _prepare_repo(
        tmp_path, feature_file="feature.txt", main_file="main-only.txt"
    )
    env = _fake_gh_env(tmp_path, ["feature.txt"])
    drift_reason = json.dumps(
        {
            "drift_from": base_sha,
            "drift_to": main_sha,
            "orthogonal_files_verified": True,
        }
    )
    result = _run_complete(
        profile,
        env=env,
        base_drift_acknowledged=True,
        drift_reason=drift_reason,
    )
    assert result.returncode == 0


def test_completion_rejects_acknowledged_nonorthogonal_base_drift(tmp_path: Path) -> None:
    _repo, profile, base_sha, main_sha = _prepare_repo(
        tmp_path, feature_file="shared.txt", main_file="shared.txt"
    )
    env = _fake_gh_env(tmp_path, ["shared.txt"])
    drift_reason = json.dumps(
        {
            "drift_from": base_sha,
            "drift_to": main_sha,
            "orthogonal_files_verified": True,
        }
    )
    result = _run_complete(
        profile,
        env=env,
        base_drift_acknowledged=True,
        drift_reason=drift_reason,
    )
    assert result.returncode != 0
    assert "base drift is not orthogonal" in result.stderr
