from pathlib import Path
import sys


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import complete_handoff


class _Profile:
    def __init__(self, root: Path) -> None:
        self.root = root

    def delivery_path(self, seat: str) -> Path:
        return self.root / "shared" / seat / "DELIVERY.md"

    def todo_path(self, seat: str) -> Path:
        return self.root / "shared" / seat / "TODO.md"

    def handoff_path(self, task_id: str, source: str, target: str) -> Path:
        return self.root / "shared" / "patrol" / f"{task_id}__{source}__{target}.json"

    def workspace_for(self, seat: str) -> Path:
        return self.root / "workspaces" / seat


def test_persist_delivery_falls_back_to_workspace(monkeypatch, tmp_path):
    profile = _Profile(tmp_path)
    writes: list[Path] = []
    primary = profile.delivery_path("qa-1")
    fallback = profile.workspace_for("qa-1") / "DELIVERY.md"

    def fake_write_delivery(path: Path, **kwargs):
        writes.append(path)
        if path == primary:
            raise PermissionError(1, "Operation not permitted", str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")

    monkeypatch.setattr(complete_handoff, "write_delivery", fake_write_delivery)

    actual, used_fallback = complete_handoff.persist_delivery(
        profile,
        seat="qa-1",
        task_id="TASK-1",
        owner="qa-1",
        target="planner",
        title="QA result",
        summary="Passed",
        status="completed",
    )

    assert used_fallback is True
    assert actual == fallback
    assert writes == [primary, fallback]


def test_persist_receipt_falls_back_to_workspace(monkeypatch, tmp_path):
    profile = _Profile(tmp_path)
    primary = profile.handoff_path("TASK-1", "qa-1", "planner")
    fallback = profile.workspace_for("qa-1") / ".clawseat" / "handoffs" / primary.name
    writes: list[Path] = []

    def fake_write_json(path: Path, payload: dict[str, object]):
        writes.append(path)
        if path == primary:
            raise PermissionError(1, "Operation not permitted", str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(complete_handoff, "write_json", fake_write_json)

    actual = complete_handoff.persist_receipt(
        profile,
        seat="qa-1",
        primary=primary,
        payload={"task_id": "TASK-1"},
    )

    assert actual == fallback
    assert writes == [primary, fallback]
