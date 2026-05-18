from pathlib import Path
import sys


_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from core.adapter.clawseat_adapter import AdapterResult, ClawseatAdapter, PendingProjectOperation


def _queued_dispatch(task_id: str) -> PendingProjectOperation:
    return PendingProjectOperation(
        kind="dispatch",
        project_name="demo",
        frontstage_epoch=1,
        profile_path="/tmp/demo-profile.toml",
        payload={
            "source": "planner",
            "target": "builder-1",
            "task_id": task_id,
            "title": f"title-{task_id}",
            "objective": f"objective-{task_id}",
        },
    )


def test_drain_pending_ops_keeps_failed_and_remaining_items(monkeypatch):
    adapter = ClawseatAdapter(repo_root=_REPO)
    adapter.current_project = "demo"
    failed = _queued_dispatch("TASK-1")
    later = _queued_dispatch("TASK-2")
    adapter._pending_inbox["demo"] = [failed, later]

    def fake_execute_dispatch(**kwargs):
        return AdapterResult(
            command=["dispatch", kwargs["task_id"]],
            returncode=1,
            stdout="",
            stderr="dispatch failed",
        )

    monkeypatch.setattr(adapter, "_execute_dispatch", fake_execute_dispatch)

    results = adapter.drain_pending_ops()

    assert len(results) == 1
    assert results[0].returncode == 1
    assert adapter._pending_inbox["demo"] == [failed, later]


def test_drain_pending_ops_removes_successful_items_before_failure(monkeypatch):
    adapter = ClawseatAdapter(repo_root=_REPO)
    adapter.current_project = "demo"
    first = _queued_dispatch("TASK-1")
    second = _queued_dispatch("TASK-2")
    third = _queued_dispatch("TASK-3")
    adapter._pending_inbox["demo"] = [first, second, third]

    outcomes = {
        "TASK-1": AdapterResult(command=["dispatch", "TASK-1"], returncode=0, stdout="ok-1", stderr=""),
        "TASK-2": AdapterResult(command=["dispatch", "TASK-2"], returncode=1, stdout="", stderr="failed-2"),
    }

    def fake_execute_dispatch(**kwargs):
        return outcomes[kwargs["task_id"]]

    monkeypatch.setattr(adapter, "_execute_dispatch", fake_execute_dispatch)

    results = adapter.drain_pending_ops()

    assert [result.returncode for result in results] == [0, 1]
    assert adapter._pending_inbox["demo"] == [second, third]
