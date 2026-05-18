from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
AGENT_ADMIN = REPO / "core" / "scripts" / "agent_admin.py"


def _iso_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _run_agent_admin(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "CLAWSEAT_SUPPRESS_TOOL_BIN_WARNING": "1",
    }
    return subprocess.run(
        [sys.executable, str(AGENT_ADMIN), *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_task_auto_supersede_marks_old_pending_without_matching_delivery(tmp_path: Path) -> None:
    home = tmp_path / "home"
    owner_dir = home / ".agents" / "tasks" / "demo" / "builder"
    owner_dir.mkdir(parents=True)
    todo = owner_dir / "TODO.md"
    todo.write_text(
        f"""# Queue: builder

## [pending] old-stale
task_id: old-stale
dispatched_at: {_iso_days_ago(5)}

### Objective

old stale task

---

## [pending] old-active
task_id: old-active
dispatched_at: {_iso_days_ago(5)}

### Objective

old task with matching delivery

---

## [pending] recent-task
task_id: recent-task
dispatched_at: {_iso_days_ago(1)}

### Objective

recent task

---

## [pending] new-task
task_id: new-task
dispatched_at: {_iso_days_ago(0)}

### Objective

new task
""",
        encoding="utf-8",
    )
    (owner_dir / "DELIVERY.md").write_text(
        "task_id: old-active\nstatus: in_progress\n",
        encoding="utf-8",
    )

    result = _run_agent_admin(home, "task", "auto-supersede", "--project", "demo", "--age-days", "3")
    assert result.returncode == 0, result.stderr
    assert "superseded\tbuilder\told-stale" in result.stdout
    assert "AUTO_SUPERSEDE project=demo count=1" in result.stdout

    text = todo.read_text(encoding="utf-8")
    assert "## [superseded] old-stale" in text
    assert "## [pending] old-active" in text
    assert "## [pending] recent-task" in text
    assert "## [pending] new-task" in text

    second = _run_agent_admin(home, "task", "auto-supersede", "--project", "demo", "--age-days", "3")
    assert second.returncode == 0, second.stderr
    assert "AUTO_SUPERSEDE project=demo count=0" in second.stdout
    assert todo.read_text(encoding="utf-8") == text


def test_patrol_loop_invokes_task_auto_supersede_each_tick() -> None:
    text = (REPO / "core" / "skills" / "gstack-harness" / "scripts" / "patrol_loop.py").read_text(
        encoding="utf-8"
    )
    assert "run_auto_supersede(profile, age_days=args.auto_supersede_age_days)" in text
    assert '"auto-supersede"' in text
