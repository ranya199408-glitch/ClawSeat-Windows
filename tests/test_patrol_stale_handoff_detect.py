from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import patrol_loop  # noqa: E402


def _handoff(home: Path, name: str, *, age_hours: float, consumed: bool = False) -> Path:
    handoffs = home / ".agents" / "tasks" / "demo" / "patrol" / "handoffs"
    handoffs.mkdir(parents=True, exist_ok=True)
    path = handoffs / f"{name}__planner__builder.json"
    path.write_text(
        json.dumps(
            {
                "task_id": name,
                "source": "planner",
                "target": "builder",
            }
        ),
        encoding="utf-8",
    )
    ts = time.time() - age_hours * 3600
    os.utime(path, (ts, ts))
    if consumed:
        path.with_suffix(".json.consumed").write_text("consumed\n", encoding="utf-8")
    return path


def test_detect_stale_handoffs_skips_fresh_and_consumed(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    fresh = _handoff(home, "fresh", age_hours=1)
    stale = _handoff(home, "stale", age_hours=patrol_loop.STALE_THRESHOLD_HOURS + 1)
    older = _handoff(home, "older", age_hours=patrol_loop.STALE_THRESHOLD_HOURS + 2)
    consumed = _handoff(home, "consumed", age_hours=patrol_loop.STALE_THRESHOLD_HOURS + 2, consumed=True)

    result = patrol_loop.detect_stale_handoffs("demo", threshold_hours=patrol_loop.STALE_THRESHOLD_HOURS)

    assert [item["task_id"] for item in result] == ["older", "stale"]
    assert {item["target"] for item in result} == {"builder"}
    assert all(item["age_hours"] >= patrol_loop.STALE_THRESHOLD_HOURS for item in result)
    assert str(fresh) not in {item["json_path"] for item in result}
    assert str(consumed) not in {item["json_path"] for item in result}
