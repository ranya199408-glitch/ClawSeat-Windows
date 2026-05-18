from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.test_complete_handoff import _dispatch, _write_profile


ROOT = Path(__file__).resolve().parents[1]
DISPATCH_SCRIPT = ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "dispatch_task.py"


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-q", "-m", "init"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/clawseat/main", head], check=True)
    return repo


def _dispatch_with_force(profile: Path, task_id: str, *, force_parallel_builder: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(DISPATCH_SCRIPT),
        "--profile",
        str(profile),
        "--source",
        "planner",
        "--target",
        "builder",
        "--task-id",
        task_id,
        "--title",
        task_id,
        "--objective",
        "objective",
        "--test-policy",
        "N/A",
        "--reply-to",
        "planner",
        "--no-notify",
    ]
    if force_parallel_builder:
        cmd.append("--force-parallel-builder")
    return subprocess.run(cmd, capture_output=True, text=True)


def test_builder_dispatch_lock_blocks_second_dispatch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    profile, handoffs, _tasks = _write_profile(tmp_path, repo)

    first = _dispatch(profile, "task-1")
    assert first.returncode == 0

    blocked = _dispatch_with_force(profile, "task-2")
    assert blocked.returncode != 0
    assert "BLOCKED: builder dispatch outstanding (task-1); awaiting __builder__planner.json" in blocked.stderr
    assert not (handoffs / "task-2__planner__builder.json").exists()


def test_force_parallel_builder_bypasses_lock(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    profile, handoffs, _tasks = _write_profile(tmp_path, repo)

    first = _dispatch(profile, "task-1")
    assert first.returncode == 0

    forced = _dispatch_with_force(profile, "task-2", force_parallel_builder=True)
    assert forced.returncode == 0
    assert "WARNING: bypassing serial dispatch lock; multi-dispatch wakeup collapse risk" in forced.stderr
    assert (handoffs / "task-2__planner__builder.json").exists()
