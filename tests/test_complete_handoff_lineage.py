from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json
import subprocess
import sys

import pytest

from tests.test_complete_handoff import _dispatch, _init_git_repo, _write_profile


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import complete_handoff  # noqa: E402


def _run_main(profile: Path, task_id: str, *, branch: str, commit: str | None = None) -> int:
    argv = [
        str(_SCRIPTS / "complete_handoff.py"),
        "--profile",
        str(profile),
        "--source",
        "builder",
        "--target",
        "planner",
        "--task-id",
        task_id,
        "--title",
        f"done {task_id}",
        "--summary",
        "completed",
        "--status",
        "completed",
        "--branch",
        branch,
        "--pr-number",
        "101",
        "--ci-conclusion",
        "success",
        "--user-summary",
        "lineage verified",
        "--no-notify",
    ]
    if commit is not None:
        argv.extend(["--commit", commit])
    old_argv = sys.argv
    sys.argv = argv
    try:
        return complete_handoff.main()
    finally:
        sys.argv = old_argv


def test_lineage_missing_fields_only_tracks_required_fields() -> None:
    receipt = {"task_id": "L-1"}

    assert complete_handoff._lineage_missing_fields(receipt) == [
        "user_summary",
        "builder_commit",
        "head_contains_commit",
        "lineage_status",
    ]


def test_lineage_missing_fields_accepts_optional_memory_commit() -> None:
    receipt = {
        "user_summary": "done",
        "builder_commit": "abc123",
        "head_contains_commit": True,
        "lineage_status": "in-lineage",
        "memory_commit": "",
    }

    assert complete_handoff._lineage_missing_fields(receipt) == []


def test_validate_completion_lineage_warns_for_grandfathered_receipt(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    receipt = {
        "task_id": "L-3",
        "created_at": (complete_handoff.LINEAGE_GRANDFATHER_CUTOFF - timedelta(days=1)).isoformat(),
    }

    complete_handoff._validate_completion_lineage(receipt, tmp_path / "receipt.json")

    assert "deprecated completion receipt format" in capsys.readouterr().err


def test_validate_completion_lineage_rejects_missing_fields_after_cutoff(tmp_path: Path) -> None:
    receipt = {
        "task_id": "L-4",
        "created_at": (complete_handoff.LINEAGE_GRANDFATHER_CUTOFF + timedelta(days=1)).isoformat(),
    }

    with pytest.raises(SystemExit) as exc_info:
        complete_handoff._validate_completion_lineage(receipt, tmp_path / "receipt.json")

    assert "missing required lineage fields after grandfather cutoff" in str(exc_info.value)


def test_receipt_reported_commit_prefers_builder_commit() -> None:
    receipt = {"builder_commit": "builder", "commit": "commit", "branch_tip": "tip"}

    assert complete_handoff._receipt_reported_commit(receipt) == "builder"


def test_receipt_reported_commit_falls_back_to_commit() -> None:
    receipt = {"commit": "commit", "branch_tip": "tip"}

    assert complete_handoff._receipt_reported_commit(receipt) == "commit"


def test_receipt_reported_commit_falls_back_to_branch_tip() -> None:
    receipt = {"branch_tip": "tip"}

    assert complete_handoff._receipt_reported_commit(receipt) == "tip"


def test_annotate_lineage_status_marks_in_lineage_and_backfills_builder_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = {"commit": "abc123"}
    monkeypatch.setattr(complete_handoff, "_git_merge_base_is_ancestor", lambda repo_root, reported_commit: True)

    status, contains, reported = complete_handoff._annotate_lineage_status(receipt, repo_root=tmp_path)

    assert status == "in-lineage"
    assert contains is True
    assert reported == "abc123"
    assert receipt["builder_commit"] == "abc123"
    assert receipt["head_contains_commit"] is True


def test_annotate_lineage_status_marks_divergent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipt = {"commit": "abc123"}
    monkeypatch.setattr(complete_handoff, "_git_merge_base_is_ancestor", lambda repo_root, reported_commit: False)

    status, contains, reported = complete_handoff._annotate_lineage_status(receipt, repo_root=tmp_path)

    assert status == "divergent"
    assert contains is False
    assert reported == "abc123"
    assert receipt["builder_commit"] == "abc123"
    assert receipt["lineage_status"] == "divergent"


def test_annotate_lineage_status_marks_unknown_without_repo_root() -> None:
    receipt = {"commit": "abc123"}

    status, contains, reported = complete_handoff._annotate_lineage_status(receipt, repo_root=None)

    assert status == "unknown"
    assert contains is False
    assert reported == "abc123"
    assert "builder_commit" not in receipt
    assert receipt["lineage_status"] == "unknown"


def test_emit_pass_needs_integration_uses_memory_channel_and_strips_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_notify(profile, target, message):  # noqa: ANN001
        calls.append((target, message))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(complete_handoff, "notify", fake_notify)
    profile = SimpleNamespace(project_name="install")

    complete_handoff._emit_pass_needs_integration(
        profile,
        task_id="L-11",
        source="builder",
        target="planner",
        reported_commit="deadbeef",
        delivery_path=Path("/tmp/delivery.md"),
        user_summary="  needs review  ",
    )

    assert len(calls) == 1
    target, message = calls[0]
    assert target == "memory"
    assert complete_handoff.PASS_NEEDS_INTEGRATION in message
    assert "lineage_status=divergent" in message
    assert "reported_commit=deadbeef" in message
    assert "user_summary=needs review" in message


def test_emit_pass_needs_integration_swallow_notify_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fake_notify(profile, target, message):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr(complete_handoff, "notify", fake_notify)
    profile = SimpleNamespace(project_name="install")

    complete_handoff._emit_pass_needs_integration(
        profile,
        task_id="L-12",
        source="builder",
        target="planner",
        reported_commit="deadbeef",
        delivery_path=Path("/tmp/delivery.md"),
        user_summary=None,
    )

    assert "warn: PASS_NEEDS_INTEGRATION notify raised" in capsys.readouterr().err


def test_main_sets_lineage_fields_for_in_lineage_completion(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path)
    profile, handoffs, _ = _write_profile(tmp_path, repo)
    assert _dispatch(profile, "L-13").returncode == 0

    assert _run_main(profile, "L-13", branch="feat/CX-test") == 0

    receipt = json.loads((handoffs / "L-13__builder__planner.json").read_text(encoding="utf-8"))
    assert receipt["head_contains_commit"] is True
    assert receipt["lineage_status"] == "in-lineage"
    assert receipt["builder_commit"] == receipt["branch_tip"]
    assert receipt["user_summary"] == "lineage verified"


def test_main_emits_pass_needs_integration_for_divergent_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _init_git_repo(tmp_path)
    profile, handoffs, _ = _write_profile(tmp_path, repo)
    assert _dispatch(profile, "L-14").returncode == 0

    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "side"], check=True)
    (repo / "SIDE.md").write_text("side\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "SIDE.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "side", "-q"], check=True)
    divergent_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "feat/CX-test"], check=True)

    calls: list[tuple[str, str]] = []

    def fake_notify(profile, target, message):  # noqa: ANN001
        calls.append((target, message))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(complete_handoff, "notify", fake_notify)
    assert _run_main(profile, "L-14", branch="feat/CX-test", commit=divergent_commit) == 0

    receipt = json.loads((handoffs / "L-14__builder__planner.json").read_text(encoding="utf-8"))
    assert receipt["head_contains_commit"] is False
    assert receipt["lineage_status"] == "divergent"
    assert receipt["builder_commit"] == divergent_commit
    assert calls and calls[0][0] == "memory"
    assert complete_handoff.PASS_NEEDS_INTEGRATION in calls[0][1]
    assert f"reported_commit={divergent_commit}" in calls[0][1]
