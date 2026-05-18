from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "core" / "skills" / "gstack-harness" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from complete_handoff import _validate_branch_lock, parse_args as complete_parse_args  # noqa: E402
from dispatch_task import _dispatch_lock_metadata, parse_args as dispatch_parse_args  # noqa: E402


def test_dispatch_cli_accepts_expected_branch_and_worktree_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dispatch_task.py",
            "--profile",
            "profile.toml",
            "--target",
            "builder-1",
            "--task-id",
            "DI-builder-worktree-lock-2026-05-07",
            "--title",
            "Lock builder worktree",
            "--objective",
            "Verify pickup metadata",
            "--test-policy",
            "N/A",
            "--expected-branch",
            "feat/custom-di-branch",
            "--expected-worktree",
            "/tmp/custom-di-wt",
        ],
    )
    args = dispatch_parse_args()
    assert args.expected_branch == "feat/custom-di-branch"
    assert args.expected_worktree == "/tmp/custom-di-wt"


def test_complete_cli_accepts_allow_branch_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "complete_handoff.py",
            "--profile",
            "profile.toml",
            "--source",
            "builder",
            "--target",
            "planner",
            "--task-id",
            "DI-builder-worktree-lock-2026-05-07",
            "--allow-branch-mismatch",
        ],
    )
    args = complete_parse_args()
    assert args.allow_branch_mismatch is True


def test_builder_dispatch_defaults_to_feat_branch_and_tmp_worktree() -> None:
    fields = _dispatch_lock_metadata(
        task_id="DI-builder-worktree-lock-2026-05-07",
        target_role="builder",
        expected_branch=None,
        expected_worktree=None,
    )
    assert fields == {
        "expected_branch": "feat/DI-builder-worktree-lock-2026-05-07",
        "expected_worktree_path": "/tmp/DI-builder-worktree-lock-2026-05-07-wt",
    }


def test_builder_dispatch_respects_explicit_overrides() -> None:
    fields = _dispatch_lock_metadata(
        task_id="DI-builder-worktree-lock-2026-05-07",
        target_role="builder",
        expected_branch="feat/custom-di-branch",
        expected_worktree="/tmp/custom-di-wt",
    )
    assert fields == {
        "expected_branch": "feat/custom-di-branch",
        "expected_worktree_path": "/tmp/custom-di-wt",
    }


def test_non_builder_dispatch_omits_lock_fields_without_overrides() -> None:
    fields = _dispatch_lock_metadata(
        task_id="DI-builder-worktree-lock-2026-05-07",
        target_role="planner",
        expected_branch=None,
        expected_worktree=None,
    )
    assert fields == {}


def test_non_builder_dispatch_preserves_explicit_lock_fields() -> None:
    fields = _dispatch_lock_metadata(
        task_id="DI-builder-worktree-lock-2026-05-07",
        target_role="planner",
        expected_branch="feat/manual-lock",
        expected_worktree="/tmp/manual-lock",
    )
    assert fields == {
        "expected_branch": "feat/manual-lock",
        "expected_worktree_path": "/tmp/manual-lock",
    }


def test_branch_lock_validation_passes_on_match() -> None:
    _validate_branch_lock(
        {"branch_tip": "feat/DI-builder-worktree-lock-2026-05-07"},
        {"expected_branch": "feat/DI-builder-worktree-lock-2026-05-07"},
        source="builder",
        target="planner",
    )


def test_branch_lock_validation_bounces_on_mismatch() -> None:
    with pytest.raises(SystemExit, match="BOUNCE: branch mismatch — expected feat/expected got feat/actual"):
        _validate_branch_lock(
            {"branch_tip": "feat/actual"},
            {"expected_branch": "feat/expected"},
            source="builder",
            target="planner",
        )


def test_branch_lock_validation_warns_when_bypassed(capsys: pytest.CaptureFixture[str]) -> None:
    _validate_branch_lock(
        {"branch_tip": "feat/actual"},
        {"expected_branch": "feat/expected"},
        source="builder",
        target="planner",
        allow_branch_mismatch=True,
    )
    captured = capsys.readouterr()
    assert "WARNING: bypassing branch lock; worktree drift risk" in captured.err


def test_legacy_dispatch_without_expected_branch_skips_validation() -> None:
    _validate_branch_lock(
        {"branch_tip": "feat/actual"},
        {"kind": "dispatch"},
        source="builder",
        target="planner",
    )


def test_branch_lock_does_not_apply_to_non_builder_to_planner_paths() -> None:
    _validate_branch_lock(
        {"branch_tip": "feat/actual"},
        {"expected_branch": "feat/expected"},
        source="planner",
        target="builder",
    )


def test_builder_skill_mentions_pickup_verification_doc() -> None:
    skill_text = (ROOT / "core" / "skills" / "builder" / "SKILL.md").read_text(encoding="utf-8")
    assert "builder-pickup-verification.md" in skill_text
    assert len(skill_text.splitlines()) < 60


def test_pickup_verification_doc_contains_core_steps() -> None:
    doc_text = (ROOT / "core" / "references" / "builder-pickup-verification.md").read_text(encoding="utf-8")
    assert "expected_branch" in doc_text
    assert "expected_worktree_path" in doc_text
    assert "pickup_verified:" in doc_text
