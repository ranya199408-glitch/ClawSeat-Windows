from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import complete_handoff


def test_planner_memory_closeout_is_final_user_visible_closeout() -> None:
    assert complete_handoff._is_final_planner_memory_closeout(
        source="planner",
        target="memory",
        source_role="planner-dispatcher",
        target_role="memory",
    )


def test_planner_project_memory_closeout_is_final_user_visible_closeout() -> None:
    assert complete_handoff._is_final_planner_memory_closeout(
        source="planner",
        target="memory",
        source_role="planner-dispatcher",
        target_role="project-memory",
    )


def test_planner_memory_closeout_does_not_require_role_metadata() -> None:
    assert complete_handoff._is_final_planner_memory_closeout(
        source="planner",
        target="memory",
        source_role="",
        target_role="",
    )


def test_builder_to_planner_is_not_final_user_visible_closeout() -> None:
    assert not complete_handoff._is_final_planner_memory_closeout(
        source="builder",
        target="planner",
        source_role="builder",
        target_role="planner-dispatcher",
    )


def test_final_planner_memory_report_uses_delegation_contract() -> None:
    text = complete_handoff._build_final_closeout_delegation_report(
        project="pbr",
        task_id="pbr-contra-001",
        summary="builder completed and planner archived to memory",
        human_summary="已完成并归档到 memory。",
    )

    assert "[OC_DELEGATION_REPORT_V1]" in text
    assert "project=pbr" in text
    assert "lane=planning" in text
    assert "task_id=pbr-contra-001" in text
    assert "report_status=done" in text
    assert "decision_hint=proceed" in text
    assert "user_gate=none" in text
    assert "next_action=finalize_chain" in text
    assert "已完成并归档到 memory。" in text


def test_final_closeout_send_uses_send_feishu_user_message(monkeypatch) -> None:
    sent = MagicMock(return_value={"status": "sent", "group_id": "oc_test"})
    monkeypatch.setattr(complete_handoff, "send_feishu_user_message", sent)

    result = complete_handoff._send_delegation_report_with_retries(
        message="[OC_DELEGATION_REPORT_V1]\nproject=pbr",
        project="pbr",
        attempts=3,
        retry_sleep_seconds=0,
    )

    assert result["status"] == "sent"
    sent.assert_called_once()
    assert sent.call_args.kwargs["project"] == "pbr"


def test_delegation_report_retry_preserves_skipped_status(monkeypatch) -> None:
    skipped = MagicMock(return_value={"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"})
    monkeypatch.setattr(complete_handoff, "send_feishu_user_message", skipped)

    result = complete_handoff._send_delegation_report_with_retries(
        message="[OC_DELEGATION_REPORT_V1]\nproject=pbr",
        project="pbr",
        attempts=3,
        retry_sleep_seconds=0,
    )

    assert result == {"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"}
    skipped.assert_called_once()


class _Profile:
    project_name = "pbr"
    heartbeat_owner = "koder"
    active_loop_owner = "memory"
    seats = ["planner", "memory"]
    seat_roles = {"planner": "planner-dispatcher", "memory": "project-memory"}

    def __init__(self, root: Path) -> None:
        self.root = root
        self.handoff_dir = root / "handoffs"
        self.status_doc = root / "STATUS.md"
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        self.status_doc.write_text("", encoding="utf-8")
        for seat in self.seats:
            (root / seat).mkdir(parents=True, exist_ok=True)

    def delivery_path(self, seat: str) -> Path:
        return self.root / seat / "DELIVERY.md"

    def todo_path(self, seat: str) -> Path:
        path = self.root / seat / "TODO.md"
        path.touch(exist_ok=True)
        return path

    def workspace_for(self, seat: str) -> Path:
        path = self.root / "workspaces" / seat
        path.mkdir(parents=True, exist_ok=True)
        return path


def _run_planner_memory_closeout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, profile: _Profile) -> None:
    argv = [
        "complete_handoff.py",
        "--profile",
        str(tmp_path / "profile.toml"),
        "--source",
        "planner",
        "--target",
        "memory",
        "--task-id",
        "pbr-closeout-1",
        "--summary",
        "done",
        "--status",
        "completed",
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        complete_handoff.main()
    finally:
        sys.argv = old_argv


def test_existing_receipt_does_not_suppress_current_final_closeout_send(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _Profile(tmp_path)
    stale_receipt = profile.handoff_dir / "pbr-closeout-1__planner__memory.json"
    stale_receipt.write_text(
        json.dumps(
            {
                "kind": "completion",
                "task_id": "pbr-closeout-1",
                "source": "planner",
                "target": "memory",
                "feishu_delegation_report": {"status": "sent", "group_id": "stale"},
            }
        ),
        encoding="utf-8",
    )
    ledger_calls: list[dict[str, object]] = []
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "notify",
        lambda _profile, _target, _message: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    sent = MagicMock(return_value={"status": "sent", "group_id": "fresh"})
    monkeypatch.setattr(complete_handoff, "send_feishu_user_message", sent)
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **kwargs: ledger_calls.append(kwargs))
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)

    _run_planner_memory_closeout(monkeypatch, tmp_path, profile)

    sent.assert_called_once()
    receipt = json.loads(stale_receipt.read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"]["group_id"] == "fresh"
    assert ledger_calls[0]["feishu_already_sent"] is True


def test_existing_receipt_does_not_mark_ledger_sent_when_current_send_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _Profile(tmp_path)
    stale_receipt = profile.handoff_dir / "pbr-closeout-1__planner__memory.json"
    stale_receipt.write_text(
        json.dumps(
            {
                "kind": "completion",
                "task_id": "pbr-closeout-1",
                "source": "planner",
                "target": "memory",
                "feishu_delegation_report": {"status": "sent", "group_id": "stale"},
            }
        ),
        encoding="utf-8",
    )
    ledger_calls: list[dict[str, object]] = []
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "notify",
        lambda _profile, _target, _message: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        complete_handoff,
        "send_feishu_user_message",
        MagicMock(side_effect=RuntimeError("feishu cli crashed")),
    )
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **kwargs: ledger_calls.append(kwargs))
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="feishu final closeout"):
        _run_planner_memory_closeout(monkeypatch, tmp_path, profile)

    receipt = json.loads(stale_receipt.read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"]["status"] == "failed"
    assert ledger_calls[0]["feishu_already_sent"] is False


@pytest.mark.parametrize("notify_returncode", [1])
def test_final_closeout_feishu_send_is_not_blocked_by_memory_notify_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    notify_returncode: int,
) -> None:
    profile = _Profile(tmp_path)
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "notify",
        lambda _profile, _target, _message: SimpleNamespace(
            returncode=notify_returncode,
            stdout="",
            stderr="memory tmux down",
        ),
    )
    sent = MagicMock(return_value={"status": "sent", "group_id": "oc_test"})
    monkeypatch.setattr(complete_handoff, "send_feishu_user_message", sent)
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **_kwargs: None)
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)
    with pytest.raises(RuntimeError, match="completion notify failed"):
        _run_planner_memory_closeout(monkeypatch, tmp_path, profile)

    sent.assert_called_once()
    receipt = json.loads((profile.handoff_dir / "pbr-closeout-1__planner__memory.json").read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"]["status"] == "sent"


def test_final_closeout_skipped_feishu_is_not_hard_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _Profile(tmp_path)
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "notify",
        lambda _profile, _target, _message: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        complete_handoff,
        "send_feishu_user_message",
        MagicMock(return_value={"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"}),
    )
    ledger_calls: list[dict[str, object]] = []
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **kwargs: ledger_calls.append(kwargs))
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)

    _run_planner_memory_closeout(monkeypatch, tmp_path, profile)

    receipt = json.loads((profile.handoff_dir / "pbr-closeout-1__planner__memory.json").read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"] == {"status": "skipped", "reason": "CLAWSEAT_FEISHU_ENABLED=0"}
    assert ledger_calls[0]["feishu_already_sent"] is False


def test_final_closeout_sender_exception_is_recorded_before_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _Profile(tmp_path)
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "notify",
        lambda _profile, _target, _message: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        complete_handoff,
        "send_feishu_user_message",
        MagicMock(side_effect=RuntimeError("feishu cli crashed")),
    )
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **_kwargs: None)
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="feishu final closeout"):
        _run_planner_memory_closeout(monkeypatch, tmp_path, profile)

    receipt = json.loads((profile.handoff_dir / "pbr-closeout-1__planner__memory.json").read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"]["status"] == "failed"
    assert "feishu cli crashed" in receipt["feishu_delegation_report"]["reason"]


def test_final_closeout_persists_when_feishu_and_memory_notify_both_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _Profile(tmp_path)
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "notify",
        lambda _profile, _target, _message: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="memory tmux down",
        ),
    )
    monkeypatch.setattr(
        complete_handoff,
        "send_feishu_user_message",
        MagicMock(side_effect=RuntimeError("feishu cli crashed")),
    )
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **_kwargs: None)
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)

    with pytest.raises(RuntimeError, match="feishu final closeout"):
        _run_planner_memory_closeout(monkeypatch, tmp_path, profile)

    receipt = json.loads((profile.handoff_dir / "pbr-closeout-1__planner__memory.json").read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"]["status"] == "failed"
    assert receipt["notify_message"]


def test_openclaw_koder_feishu_failure_is_recorded_before_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    profile = _Profile(tmp_path)
    profile.active_loop_owner = "planner"
    profile.heartbeat_owner = "koder"
    profile.seats = ["planner", "memory", "koder"]
    (tmp_path / "koder").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(complete_handoff, "load_profile", lambda _path: profile)
    monkeypatch.setattr(
        complete_handoff,
        "resolve_seat_from_profile",
        lambda _target, _profile: SimpleNamespace(kind="openclaw"),
    )
    monkeypatch.setattr(
        complete_handoff,
        "send_feishu_user_message",
        MagicMock(side_effect=RuntimeError("feishu cli crashed")),
    )
    monkeypatch.setattr(complete_handoff, "_write_completion_to_ledger", lambda **_kwargs: None)
    monkeypatch.setattr(complete_handoff, "_try_announce_planner_event", lambda **_kwargs: None)
    argv = [
        "complete_handoff.py",
        "--profile",
        str(tmp_path / "profile.toml"),
        "--source",
        "planner",
        "--target",
        "koder",
        "--task-id",
        "pbr-koder-1",
        "--summary",
        "done",
        "--status",
        "completed",
        "--frontstage-disposition",
        "AUTO_ADVANCE",
    ]
    old_argv = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(RuntimeError, match="feishu openclaw koder"):
            complete_handoff.main()
    finally:
        sys.argv = old_argv

    receipt = json.loads((profile.handoff_dir / "pbr-koder-1__planner__koder.json").read_text(encoding="utf-8"))
    assert receipt["feishu_delegation_report"]["status"] == "failed"
    assert "feishu cli crashed" in receipt["feishu_delegation_report"]["reason"]
