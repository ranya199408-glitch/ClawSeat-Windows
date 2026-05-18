from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts" / "complete_handoff.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "builder@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Builder"], check=True)

    (repo / "README.md").write_text("main\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "main", "-q"], check=True)
    main_sha = _git(repo, "rev-parse", "HEAD")
    subprocess.run(["git", "-C", str(repo), "branch", "clawseat/main"], check=True)

    subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat/planner-self-closeout", "-q"], check=True)
    (repo / "README.md").write_text("main\nfeature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "commit", "-am", "feature", "-q"], check=True)
    feature_sha = _git(repo, "rev-parse", "HEAD")
    return repo, main_sha, feature_sha, "feat/planner-self-closeout"


def _write_profile(tmp_path: Path, repo_root: Path) -> Path:
    tasks_root = tmp_path / "tasks"
    workspace_root = tmp_path / "workspace"
    handoff_dir = tasks_root / "patrol" / "handoffs"
    planner_dir = tasks_root / "planner"
    memory_dir = tasks_root / "memory"
    builder_dir = tasks_root / "builder"
    for path in (
        handoff_dir,
        planner_dir,
        memory_dir,
        builder_dir,
        workspace_root / "planner",
        workspace_root / "memory",
        workspace_root / "builder",
    ):
        path.mkdir(parents=True, exist_ok=True)

    (tasks_root / "STATUS.md").write_text(
        "# Status\n\n## dispatch log (append-only, last 20)\n\n(none)\n",
        encoding="utf-8",
    )
    (tasks_root / "PROJECT.md").write_text("# Project\n", encoding="utf-8")
    (tasks_root / "TASKS.md").write_text("# Tasks\n", encoding="utf-8")

    send_script = tmp_path / "send.sh"
    status_script = tmp_path / "status.sh"
    patrol_script = tmp_path / "patrol.sh"
    heartbeat_receipt = tmp_path / "heartbeat.toml"
    for path in (send_script, status_script, patrol_script):
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    heartbeat_receipt.write_text("", encoding="utf-8")

    profile = tmp_path / "profile.toml"
    profile.write_text(
        dedent(
            f"""\
            profile_name = "install-test"
            template_name = "install-test"
            project_name = "install"
            repo_root = "{repo_root}"
            tasks_root = "{tasks_root}"
            project_doc = "{tasks_root / 'PROJECT.md'}"
            tasks_doc = "{tasks_root / 'TASKS.md'}"
            status_doc = "{tasks_root / 'STATUS.md'}"
            send_script = "{send_script}"
            status_script = "{status_script}"
            patrol_script = "{patrol_script}"
            agent_admin = "/bin/true"
            workspace_root = "{workspace_root}"
            handoff_dir = "{handoff_dir}"
            heartbeat_owner = "planner"
            heartbeat_transport = "tmux"
            active_loop_owner = "planner"
            default_notify_target = "memory"
            heartbeat_receipt = "{heartbeat_receipt}"
            seats = ["planner", "memory", "builder"]
            heartbeat_seats = ["planner"]

            [seat_roles]
            planner = "planner"
            memory = "memory"
            builder = "builder"
            """
        ),
        encoding="utf-8",
    )
    return profile


def _incoming_receipt_path(profile: Path, task_id: str) -> Path:
    handoff_dir = profile.parent / "tasks" / "patrol" / "handoffs"
    return handoff_dir / f"{task_id}__builder__planner.json"


def _consumed_receipt_path(profile: Path, task_id: str) -> Path:
    path = _incoming_receipt_path(profile, task_id)
    return path.with_name(f"{path.name}.consumed")


def _delivery_path(profile: Path) -> Path:
    return profile.parent / "tasks" / "planner" / "DELIVERY.md"


def _completion_path(profile: Path, task_id: str) -> Path:
    return profile.parent / "tasks" / "patrol" / "handoffs" / f"{task_id}__planner__memory.json"


def _run_complete(profile: Path, task_id: str, *args: str, summary: str = "builder summary") -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--profile",
        str(profile),
        "--source",
        "planner",
        "--target",
        "memory",
        "--task-id",
        task_id,
        "--summary",
        summary,
        "--no-notify",
        *args,
    ]
    return subprocess.run(cmd, check=False, capture_output=True, text=True)


def test_planner_completion_consumes_builder_receipt(tmp_path: Path) -> None:
    repo, _, _, _ = _init_repo(tmp_path)
    profile = _write_profile(tmp_path, repo)
    task_id = "DH-self-closeout-consume"
    incoming = _incoming_receipt_path(profile, task_id)
    incoming.write_text(
        json.dumps(
            {
                "kind": "dispatch",
                "task_id": task_id,
                "source": "builder",
                "target": "planner",
            }
        ),
        encoding="utf-8",
    )

    result = _run_complete(profile, task_id)

    assert result.returncode == 0, result.stderr
    assert not incoming.exists()
    assert _consumed_receipt_path(profile, task_id).exists()
    assert _delivery_path(profile).exists()


def test_planner_completion_writes_delivery_metadata(tmp_path: Path) -> None:
    repo, main_sha, feature_sha, branch_name = _init_repo(tmp_path)
    profile = _write_profile(tmp_path, repo)
    task_id = "DH-self-closeout-metadata"
    incoming = _incoming_receipt_path(profile, task_id)
    incoming.write_text(
        json.dumps(
            {
                "kind": "dispatch",
                "task_id": task_id,
                "source": "builder",
                "target": "planner",
            }
        ),
        encoding="utf-8",
    )

    result = _run_complete(
        profile,
        task_id,
        "--branch",
        branch_name,
        "--commit",
        feature_sha,
        "--sweep-count",
        "7",
        summary="builder summary line",
    )

    assert result.returncode == 0, result.stderr
    delivery = _delivery_path(profile).read_text(encoding="utf-8")
    assert f"branch: {branch_name}" in delivery
    assert f"commit: {feature_sha}" in delivery
    assert "sweep_count: 7" in delivery
    assert "builder summary line" in delivery

    receipt = json.loads(_completion_path(profile, task_id).read_text(encoding="utf-8"))
    assert receipt["branch"] == branch_name
    assert receipt["commit"] == feature_sha
    assert receipt["sweep_count"] == 7
    assert receipt["branch_base"] == main_sha
    assert receipt["branch_tip"] == feature_sha


def test_planner_completion_without_incoming_receipt_is_ok(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = _write_profile(tmp_path, repo)
    task_id = "DH-self-closeout-missing"

    result = _run_complete(profile, task_id)

    assert result.returncode == 0, result.stderr
    assert _delivery_path(profile).exists()
    assert "skip rename" in result.stderr


def test_planner_completion_escape_hatch_skips_self_closeout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = _write_profile(tmp_path, repo)
    task_id = "DH-self-closeout-bypass"
    incoming = _incoming_receipt_path(profile, task_id)
    incoming.write_text(
        json.dumps(
            {
                "kind": "dispatch",
                "task_id": task_id,
                "source": "builder",
                "target": "planner",
            }
        ),
        encoding="utf-8",
    )

    result = _run_complete(profile, task_id, "--enforce-planner-self-closeout=false")

    assert result.returncode == 0, result.stderr
    assert incoming.exists()
    assert not _consumed_receipt_path(profile, task_id).exists()
    assert not _delivery_path(profile).exists()
    assert "WARNING: bypassing planner self-closeout; .consumed + DELIVERY.md may drift" in result.stderr


def test_planner_completion_idempotent_when_consumed_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = _write_profile(tmp_path, repo)
    task_id = "DH-self-closeout-idempotent"
    consumed = _consumed_receipt_path(profile, task_id)
    consumed.write_text(
        json.dumps(
            {
                "kind": "dispatch",
                "task_id": task_id,
                "source": "builder",
                "target": "planner",
            }
        ),
        encoding="utf-8",
    )

    result = _run_complete(profile, task_id)

    assert result.returncode == 0, result.stderr
    assert consumed.exists()
    assert not _incoming_receipt_path(profile, task_id).exists()
    assert _delivery_path(profile).exists()
