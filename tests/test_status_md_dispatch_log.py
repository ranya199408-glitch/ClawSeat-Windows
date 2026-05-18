from __future__ import annotations

import json
import fcntl
import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]

import _task_io


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_DISPATCH_LOG = "## dispatch log (append-only, last 20)"


def _status_doc(entries: list[str] | None = None) -> str:
    body = "\n".join(entries or [])
    return (
        "# test — STATUS\n\n"
        "## phase\n\n"
        "phase=ready\n\n"
        "## dispatch log (append-only, last 20)\n\n"
        f"{body}\n"
    )


def _dispatch_log_entries(text: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index(_DISPATCH_LOG) + 1
    end = len(lines)
    for idx in range(start, len(lines)):
        if idx > start and lines[idx].startswith("## "):
            end = idx
            break
    return [
        line
        for line in lines[start:end]
        if line.strip() and line.strip() != "(none)"
    ]


def _audit_dir(profile: Path) -> Path:
    data = tomllib.loads(profile.read_text(encoding="utf-8"))
    return Path(data["handoff_dir"]) / "audit"


def _make_profile(
    tmp_path: Path,
    *,
    status_text: str | None = None,
    repo_root: Path | None = None,
) -> tuple[Path, Path]:
    tasks = tmp_path / "tasks" / "install"
    workspaces = tmp_path / "workspaces" / "install"
    handoffs = tasks / "patrol" / "handoffs"
    status = tasks / "STATUS.md"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text(status_text if status_text is not None else _status_doc(), encoding="utf-8")
    repo_root = repo_root or (tmp_path / "missing-repo")

    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "install"
repo_root = "{repo_root}"
tasks_root = "{tasks}"
project_doc = "{tasks / "PROJECT.md"}"
tasks_doc = "{tasks / "TASKS.md"}"
status_doc = "{status}"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
workspace_root = "{workspaces}"
handoff_dir = "{handoffs}"
heartbeat_owner = "koder"
heartbeat_transport = "tmux"
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_receipt = "{workspaces / "koder" / "HEARTBEAT_RECEIPT.toml"}"
seats = ["planner", "builder"]
heartbeat_seats = []

[seat_roles]
planner = "planner-dispatcher"
builder = "builder"

[dynamic_roster]
materialized_seats = ["planner", "builder"]
runtime_seats = ["planner", "builder"]
""",
        encoding="utf-8",
    )
    return profile, status


def _init_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "ci"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "ci@example.com"], check=True)

    (repo / "README.md").write_text("main\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "main", "-q"], check=True)

    main_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "update-ref", "refs/remotes/clawseat/main", main_sha], check=True)

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat/status-ack"], check=True)
    (repo / "FEATURE.md").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "FEATURE.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "feature branch", "-q"], check=True)
    return repo


def _run_dispatch(profile: Path, task_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "dispatch_task.py"),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target",
            "builder",
            "--task-id",
            task_id,
            "--title",
            f"test {task_id}",
            "--objective",
            "no-op objective",
            "--test-policy",
            "UPDATE",
            "--reply-to",
            "planner",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )


def _run_complete(
    profile: Path,
    task_id: str,
    *,
    branch: str | None = None,
    pr_number: str | None = None,
    ci_conclusion: str | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable,
        str(_SCRIPTS / "complete_handoff.py"),
        "--profile",
        str(profile),
        "--source",
        "builder",
        "--target",
        "planner",
        "--task-id",
        task_id,
        "--summary",
        "no-op done",
        "--status",
        "done",
        "--verdict",
        "APPROVED",
        "--commit",
        "abc1234",
        "--no-notify",
    ]
    if branch:
        args.extend(["--branch", branch])
    if pr_number:
        args.extend(["--pr-number", pr_number])
    if ci_conclusion:
        args.extend(["--ci-conclusion", ci_conclusion])
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )


def test_dispatch_appends_line(tmp_path: Path) -> None:
    profile, status = _make_profile(tmp_path)

    result = _run_dispatch(profile, "status-dispatch")

    assert result.returncode == 0, result.stderr
    entries = _dispatch_log_entries(status.read_text(encoding="utf-8"))
    assert len(entries) == 1
    assert entries[0].endswith(": planner dispatched status-dispatch to builder test_policy=UPDATE")


def test_complete_appends_ack(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    profile, status = _make_profile(tmp_path, repo_root=repo)
    dispatch = _run_dispatch(profile, "status-ack")
    assert dispatch.returncode == 0, dispatch.stderr

    result = _run_complete(
        profile,
        "status-ack",
        branch="feat/status-ack",
        pr_number="101",
        ci_conclusion="success",
    )

    assert result.returncode == 0, result.stderr
    entries = _dispatch_log_entries(status.read_text(encoding="utf-8"))
    assert entries[-1].endswith(": builder ack status-ack test_policy=UPDATE verdict=APPROVED commit=abc1234")


def test_truncation_keeps_last_20(tmp_path: Path) -> None:
    old_entries = [
        f"- 2026-04-26T00:{idx:02d}:00+08:00: planner dispatched old-{idx:02d} to builder"
        for idx in range(22)
    ]
    profile, status = _make_profile(tmp_path, status_text=_status_doc(old_entries))

    result = _run_dispatch(profile, "status-truncate")

    assert result.returncode == 0, result.stderr
    entries = _dispatch_log_entries(status.read_text(encoding="utf-8"))
    assert len(entries) == 20
    assert "old-00" not in "\n".join(entries)
    assert "old-01" not in "\n".join(entries)
    assert "old-02" not in "\n".join(entries)
    assert entries[-1].endswith(": planner dispatched status-truncate to builder test_policy=UPDATE")


def test_missing_section_auto_heals_and_writes_audit(tmp_path: Path) -> None:
    before = "# test — STATUS\n\n## phase\n\nphase=ready\n"
    profile, status = _make_profile(tmp_path, status_text=before)

    result = _run_dispatch(profile, "status-missing-section")

    assert result.returncode == 0
    repaired = status.read_text(encoding="utf-8")
    assert _DISPATCH_LOG in repaired
    assert "planner dispatched status-missing-section to builder" in repaired
    assert "INFO: STATUS.md dispatch-log section auto-healed" in result.stderr
    audit_files = sorted(_audit_dir(profile).glob("dispatch-log-heal-*.json"))
    assert len(audit_files) == 1
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["task_id"] == "status-missing-section"
    assert audit["reason"] == "section_absent"


def test_atomic_write(tmp_path: Path, monkeypatch) -> None:
    status = tmp_path / "STATUS.md"
    status.write_text(_status_doc(), encoding="utf-8")
    calls: list[tuple[Path, Path]] = []
    real_replace = os.replace

    def fake_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
        src_path = Path(src)
        dst_path = Path(dst)
        calls.append((src_path, dst_path))
        assert src_path.name == "STATUS.md.tmp"
        assert src_path.exists()
        assert "planner dispatched atomic-task to builder" in src_path.read_text(encoding="utf-8")
        real_replace(src_path, dst_path)

    monkeypatch.setattr(_task_io.os, "replace", fake_replace)

    ok = _task_io.append_status_dispatch_event(
        status,
        source="planner",
        task_id="atomic-task",
        target="builder",
        timestamp="2026-04-26T05:00:00+08:00",
    )

    assert ok is True
    assert calls == [(status.with_name("STATUS.md.tmp"), status)]
    assert "planner dispatched atomic-task to builder" in status.read_text(encoding="utf-8")


def test_append_uses_flock_lockfile(tmp_path: Path, monkeypatch) -> None:
    status = tmp_path / "STATUS.md"
    status.write_text(_status_doc(), encoding="utf-8")
    calls: list[int] = []
    real_flock = _task_io.fcntl.flock

    def fake_flock(fd: int, operation: int) -> None:
        calls.append(operation)
        real_flock(fd, operation)

    monkeypatch.setattr(_task_io.fcntl, "flock", fake_flock)

    ok = _task_io.append_status_dispatch_event(
        status,
        source="planner",
        task_id="locked-task",
        target="builder",
        timestamp="2026-04-26T05:00:00+08:00",
    )

    assert ok is True
    assert calls == [fcntl.LOCK_EX, fcntl.LOCK_UN]
    assert status.with_name("STATUS.md.lock").exists()
