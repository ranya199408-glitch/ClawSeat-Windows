"""CX: dispatch_task records expected_base_sha and lineage receipt fields."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_DISPATCH = _SCRIPTS / "dispatch_task.py"


def _run(*cmd: str, cwd: Path | str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_DISPATCH), *cmd],
        capture_output=True,
        text=True,
        cwd=str(cwd or _SCRIPTS),
        check=False,
    )


def _write_profile(tmp_path: Path, repo_root: Path) -> tuple[Path, Path]:
    tasks = tmp_path / "tasks"
    handoffs = tmp_path / "handoffs"
    workspaces = tmp_path / "workspaces"
    tasks.mkdir()
    (tasks / "planner").mkdir()
    (tasks / "builder").mkdir()
    handoffs.mkdir()
    workspaces.mkdir()
    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = \"test-profile\"
project_name = \"test\"
template_name = \"gstack-harness\"
repo_root = \"{repo_root}\"
tasks_root = \"{tasks}\"
workspace_root = \"{workspaces}\"
handoff_dir = \"{handoffs}\"
project_doc = \"{tasks}/PROJECT.md\"
tasks_doc = \"{tasks}/TASKS.md\"
status_doc = \"{tasks}/STATUS.md\"
send_script = \"/bin/echo\"
status_script = \"/bin/echo\"
patrol_script = \"/bin/echo\"
agent_admin = \"/bin/echo\"
heartbeat_receipt = \"{workspaces}/koder/HEARTBEAT_RECEIPT.toml\"
heartbeat_transport = \"tmux\"
default_notify_target = \"planner\"
heartbeat_owner = \"koder\"
heartbeat_seats = []
active_loop_owner = \"planner\"
seats = [\"planner\", \"builder\"]

[seat_roles]
planner = \"planner-dispatcher\"
builder = \"builder\"

[dynamic_roster]
materialized_seats = [\"planner\", \"builder\"]
""",
        encoding="utf-8",
    )
    return profile, handoffs


def _write_profile_with_memory(tmp_path: Path, repo_root: Path) -> tuple[Path, Path]:
    tasks = tmp_path / "tasks"
    handoffs = tmp_path / "handoffs"
    workspaces = tmp_path / "workspaces"
    tasks.mkdir()
    (tasks / "planner").mkdir()
    (tasks / "builder").mkdir()
    (tasks / "memory").mkdir()
    handoffs.mkdir()
    workspaces.mkdir()
    profile = tmp_path / "profile.toml"
    profile.write_text(
        f"""\
version = 1
profile_name = \"test-profile\"
project_name = \"test\"
template_name = \"gstack-harness\"
repo_root = \"{repo_root}\"
tasks_root = \"{tasks}\"
workspace_root = \"{workspaces}\"
handoff_dir = \"{handoffs}\"
project_doc = \"{tasks}/PROJECT.md\"
tasks_doc = \"{tasks}/TASKS.md\"
status_doc = \"{tasks}/STATUS.md\"
send_script = \"/bin/echo\"
status_script = \"/bin/echo\"
patrol_script = \"/bin/echo\"
agent_admin = \"/bin/echo\"
heartbeat_receipt = \"{workspaces}/koder/HEARTBEAT_RECEIPT.toml\"
heartbeat_transport = \"tmux\"
default_notify_target = \"planner\"
heartbeat_owner = \"koder\"
heartbeat_seats = []
active_loop_owner = \"memory\"
seats = [\"planner\", \"builder\", \"memory\"]

[seat_roles]
planner = \"planner-dispatcher\"
builder = \"builder\"
memory = \"memory\"

[dynamic_roster]
materialized_seats = [\"planner\", \"builder\", \"memory\"]
""",
        encoding="utf-8",
    )
    return profile, handoffs


def _init_repo(repo_root: Path) -> str:
    repo_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(repo_root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "ci"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "ci@example.com"],
        check=True,
    )
    (repo_root / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "init", "-q"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-q", "-B", "main"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo_root), "update-ref", "refs/remotes/clawseat/main", head],
        check=True,
    )
    return head


def _rev_parse(repo_root: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _dispatch(
    profile: Path,
    task_id: str,
    *,
    source: str = "planner",
    finding_id: str | None = None,
    rca_override: bool = False,
    core_ux: bool = False,
    target: str = "builder",
) -> subprocess.CompletedProcess[str]:
    args = [
        "--profile", str(profile),
        "--source", source,
        "--target", target,
        "--task-id", task_id,
        "--title", f"test {task_id}",
        "--objective", "run",
        "--test-policy", "UPDATE",
        "--reply-to", "planner",
        "--no-notify",
    ]
    if finding_id:
        args.extend(["--finding-id", finding_id])
    if rca_override:
        args.append("--rca-override")
    if core_ux:
        args.append("--core-ux")
    return _run(*args)


def test_dispatch_records_expected_base_sha_when_git_main_known(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    expected = _init_repo(repo_root)
    profile, handoffs = _write_profile(tmp_path, repo_root)

    result = _dispatch(profile, "TASK-BASE-1")
    assert result.returncode == 0, result.stderr

    receipt = handoffs / "TASK-BASE-1__planner__builder.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["expected_base_sha"] == expected
    assert payload["builder_commit"] == expected
    assert payload["memory_commit"] is None
    assert payload["head_contains_commit"] is True
    assert payload["lineage_status"] == "in-lineage"


def test_builder_dispatch_advances_task_branch_ref_to_current_main(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    initial = _init_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-q", "-b", "feat/TASK-BRANCH", initial],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-q", "main"], check=True)
    (repo_root / "README.md").write_text("main v2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "advance main", "-q"], check=True)
    expected = _rev_parse(repo_root, "HEAD")
    subprocess.run(
        ["git", "-C", str(repo_root), "update-ref", "refs/remotes/clawseat/main", expected],
        check=True,
    )
    profile, handoffs = _write_profile(tmp_path, repo_root)

    result = _dispatch(profile, "TASK-BRANCH")
    assert result.returncode == 0, result.stderr

    receipt = handoffs / "TASK-BRANCH__planner__builder.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["expected_base_sha"] == expected
    assert _rev_parse(repo_root, "feat/TASK-BRANCH") == expected


def test_dispatch_skips_expected_base_sha_when_git_main_missing(tmp_path: Path) -> None:
    profile, handoffs = _write_profile(tmp_path, tmp_path / "missing-repo")
    result = _dispatch(profile, "TASK-BASE-2")
    assert result.returncode == 0, result.stderr

    receipt = handoffs / "TASK-BASE-2__planner__builder.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert "expected_base_sha" not in payload
    assert payload["builder_commit"] is None
    assert payload["memory_commit"] is None
    assert payload["head_contains_commit"] is False
    assert payload["lineage_status"] == "unknown"


def test_dispatch_records_memory_commit_for_memory_source(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    expected = _init_repo(repo_root)
    profile, handoffs = _write_profile_with_memory(tmp_path, repo_root)

    result = _dispatch(profile, "TASK-MEM-1", source="memory")
    assert result.returncode == 0, result.stderr

    receipt = handoffs / "TASK-MEM-1__memory__builder.json"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["expected_base_sha"] == expected
    assert payload["builder_commit"] == expected
    assert payload["memory_commit"] == expected
    assert payload["head_contains_commit"] is True
    assert payload["lineage_status"] == "in-lineage"


def test_dispatch_records_finding_id_and_counter(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _init_repo(repo_root)
    profile, handoffs = _write_profile(tmp_path, repo_root)
    finding_id = "install-finding-hypo"

    first = _dispatch(profile, "H1", finding_id=finding_id)
    assert first.returncode == 0, first.stderr
    first_payload = json.loads(
        (handoffs / "H1__planner__builder.json").read_text(encoding="utf-8")
    )
    assert first_payload["finding_id"] == finding_id
    assert first_payload["hypothesis_fix_counter"] == 0
    assert first_payload["hypothesis_fix_counter_exceeded"] is False

    second = _dispatch(profile, "H2", finding_id=finding_id)
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(
        (handoffs / "H2__planner__builder.json").read_text(encoding="utf-8")
    )
    assert second_payload["hypothesis_fix_counter"] == 1
    assert second_payload["hypothesis_fix_counter_exceeded"] is False


def test_dispatch_warns_when_hypothesis_counter_exceeds_without_rca_override(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    _init_repo(repo_root)
    profile, handoffs = _write_profile(tmp_path, repo_root)
    finding_id = "install-finding-exceeded"

    for i in range(3):
        result = _dispatch(profile, f"EX-{i}", finding_id=finding_id)
        assert result.returncode == 0, result.stderr

    result = _dispatch(profile, "EX-4", finding_id=finding_id)
    assert result.returncode == 0, result.stderr
    assert "hypothesis_fix_counter exceeded" in result.stderr

    payload = json.loads(
        (handoffs / "EX-4__planner__builder.json").read_text(encoding="utf-8")
    )
    assert payload["finding_id"] == finding_id
    assert payload["hypothesis_fix_counter"] == 3
    assert payload["hypothesis_fix_counter_exceeded"] is True
    assert payload["rca_override"] is None

    result_override = _dispatch(profile, "EX-5", finding_id=finding_id, rca_override=True)
    assert result_override.returncode == 0, result_override.stderr
    override_payload = json.loads(
        (handoffs / "EX-5__planner__builder.json").read_text(encoding="utf-8")
    )
    assert override_payload["rca_override"] is True
