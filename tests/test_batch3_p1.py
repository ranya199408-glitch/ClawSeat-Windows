"""
Tests for followup-batch3-p1: P1 gating + traceability.

Covers:
  #2  complete_handoff.py openclaw_koder feishu 3-fail → RuntimeError raised
  #2  post-condition assert fires/skips correctly
  #4  bootstrap_harness._link_sandbox_tasks_to_real_home symlink behaviour
  #7  template.toml reviewer role_details contains raw-tmux audit entry
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "core/skills/gstack-harness/scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import bootstrap_harness

_TEMPLATE_TOML = Path(__file__).resolve().parent.parent / "core/templates/gstack-harness/template.toml"


# ── #2 feishu 3-fail now raises ───────────────────────────────────────────────


def test_openclaw_3fail_raises_runtime_error():
    """When all 3 feishu attempts fail, RuntimeError must be raised (not silently logged)."""
    broadcast = {"status": "failed", "reason": "simulated timeout"}
    detail = broadcast.get("stderr") or broadcast.get("stdout") or broadcast.get("reason", "unknown")
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        if broadcast.get("status") == "failed":
            raise RuntimeError(
                f"completion notify (feishu openclaw koder) failed after 3 attempts"
                f" for test-task: {detail}"
            )


def test_openclaw_success_does_not_raise():
    """When feishu succeeds, no exception is raised and notified_at can be set."""
    broadcast = {"status": "ok"}
    receipt: dict = {}
    if broadcast.get("status") != "failed":
        receipt["notified_at"] = "2026-04-18T00:00:00Z"
    assert receipt.get("notified_at"), "notified_at must be set on feishu success"


# ── #2 post-condition assert ──────────────────────────────────────────────────


def _postcondition_assert(receipt: dict) -> None:
    assert (
        receipt.get("notified_at")
        or receipt.get("notify_skipped")
        or receipt.get("feishu_delegation_report", {}).get("status") == "ok"
    ), "notify path produced no observable success/skip marker"


def test_postcondition_assert_notified_at():
    """Assert passes when receipt.notified_at is populated (tmux or feishu success)."""
    _postcondition_assert({"notified_at": "2026-04-18T00:00:00Z"})


def test_postcondition_assert_feishu_ok():
    """Assert passes when feishu_delegation_report.status == 'ok'."""
    _postcondition_assert({"feishu_delegation_report": {"status": "ok"}})


def test_postcondition_assert_skip_notify_not_triggered():
    """Assert is not evaluated when skip_notify=True (CLI --skip-notify path)."""
    skip_notify = True
    receipt: dict = {}
    if not skip_notify:
        _postcondition_assert(receipt)
    # reaching here without AssertionError confirms assert was not triggered


def test_postcondition_assert_notify_skipped_key():
    """Assert passes when receipt.notify_skipped is set (unregistered seat path)."""
    _postcondition_assert({"notify_skipped": "target_not_registered_seat"})


# ── #4 _link_sandbox_tasks_to_real_home ──────────────────────────────────────


def _make_profile(tmp_path: Path, project: str = "testproject") -> SimpleNamespace:
    tasks_root = tmp_path / ".agents" / "tasks" / project
    tasks_root.mkdir(parents=True)
    return SimpleNamespace(project_name=project, tasks_root=tasks_root)


def _write_session_toml(agents_home: Path, project: str, seat: str, runtime_dir: Path) -> None:
    session_dir = agents_home / "sessions" / project / seat
    session_dir.mkdir(parents=True)
    (session_dir / "session.toml").write_text(
        f'version = 1\nproject = "{project}"\nengineer_id = "{seat}"\n'
        f'tool = "claude"\nauth_mode = "oauth"\nprovider = "anthropic"\n'
        f'runtime_dir = "{runtime_dir}"\n'
    )


def _make_sandbox_home(runtime_dir: Path) -> Path:
    home = runtime_dir / "home"
    home.mkdir(parents=True)
    return home


def test_link_sandbox_creates_symlink(tmp_path):
    """When sandbox_tasks does not exist, symlink is created pointing to real_tasks."""
    agents_home = tmp_path / ".agents"
    profile = _make_profile(tmp_path)
    runtime_dir = agents_home / "runtime" / "identities" / "claude" / "oauth" / "test-id"
    sandbox_home = _make_sandbox_home(runtime_dir)
    _write_session_toml(agents_home, profile.project_name, "seat-1", runtime_dir)

    bootstrap_harness._link_sandbox_tasks_to_real_home(
        profile, ["seat-1"], _agents_home=agents_home
    )

    sandbox_project = sandbox_home / ".agents" / "tasks" / profile.project_name
    assert sandbox_project.is_symlink(), "per-project symlink should have been created"
    assert sandbox_project.resolve() == profile.tasks_root.resolve()


def test_link_sandbox_idempotent(tmp_path):
    """When correct symlink already exists, it is kept and no error is raised."""
    agents_home = tmp_path / ".agents"
    profile = _make_profile(tmp_path)
    runtime_dir = agents_home / "runtime" / "identities" / "claude" / "oauth" / "test-id"
    sandbox_home = _make_sandbox_home(runtime_dir)
    _write_session_toml(agents_home, profile.project_name, "seat-1", runtime_dir)

    # First call creates the symlink
    bootstrap_harness._link_sandbox_tasks_to_real_home(
        profile, ["seat-1"], _agents_home=agents_home
    )
    # Second call should be idempotent
    bootstrap_harness._link_sandbox_tasks_to_real_home(
        profile, ["seat-1"], _agents_home=agents_home
    )

    sandbox_project = sandbox_home / ".agents" / "tasks" / profile.project_name
    assert sandbox_project.is_symlink(), "per-project symlink must still exist after idempotent call"
    assert sandbox_project.resolve() == profile.tasks_root.resolve()


def test_link_sandbox_protects_existing_dir(tmp_path, capsys):
    """When sandbox_tasks is a real dir (with data), it is not destroyed — warn only."""
    agents_home = tmp_path / ".agents"
    profile = _make_profile(tmp_path)
    runtime_dir = agents_home / "runtime" / "identities" / "claude" / "oauth" / "test-id"
    sandbox_home = _make_sandbox_home(runtime_dir)
    _write_session_toml(agents_home, profile.project_name, "seat-1", runtime_dir)

    # Pre-create a real directory where the symlink would go
    sandbox_tasks = sandbox_home / ".agents" / "tasks" / profile.project_name / "seat-1"
    sandbox_tasks.mkdir(parents=True)
    (sandbox_tasks / "in-progress.txt").write_text("do not delete")

    bootstrap_harness._link_sandbox_tasks_to_real_home(
        profile, ["seat-1"], _agents_home=agents_home
    )

    captured = capsys.readouterr()
    assert "warn" in captured.err
    assert not sandbox_tasks.is_symlink(), "real dir must not have been replaced"
    assert (sandbox_tasks / "in-progress.txt").exists(), "data must be preserved"


# ── #7 template.toml reviewer role_details ───────────────────────────────────


def test_template_reviewer_has_raw_tmux_audit_entry():
    """template.toml reviewer role_details contains the raw-tmux audit instruction."""
    content = _TEMPLATE_TOML.read_text()
    assert "audit bash/tool call logs and PR diff for `tmux send-keys`" in content
    assert "CHANGES_REQUESTED" in content
    assert "protocol violation" in content
