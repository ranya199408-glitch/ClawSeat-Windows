#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

from real_home import real_user_home  # noqa: E402


HOME = real_user_home()
TASKS_ROOT = HOME / ".agents" / "tasks"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect peer activity and report progressing/idle/stalled.")
    parser.add_argument("--project", required=True, help="Owning install project.")
    parser.add_argument("--peer-id", required=True, help="Peer identifier.")
    parser.add_argument("--task-id", help="Optional task id to narrow the scan.")
    parser.add_argument("--progress-window", type=int, default=120, help="Seconds considered progressing.")
    parser.add_argument("--stall-window", type=int, default=900, help="Seconds considered stalled.")
    return parser.parse_args()


def _candidate_files(peer_root: Path, task_id: str | None) -> list[Path]:
    paths: list[Path] = []
    for name in ("meta.json", "heartbeat.json"):
        candidate = peer_root / name
        if candidate.exists():
            paths.append(candidate)

    if task_id:
        task_dir = peer_root / "tasks" / task_id
        if task_dir.exists():
            for child in sorted(task_dir.iterdir()):
                if child.is_file():
                    paths.append(child)
    elif peer_root.exists():
        tasks_dir = peer_root / "tasks"
        if tasks_dir.exists():
            for child in sorted(tasks_dir.rglob("*")):
                if child.is_file():
                    paths.append(child)

    seen: set[Path] = set()
    deduped: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _latest_activity(paths: list[Path]) -> tuple[float | None, Path | None]:
    latest_mtime: float | None = None
    latest_path: Path | None = None
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if latest_mtime is None or mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path
    return latest_mtime, latest_path


def _state_for_age(age_seconds: float | None, progress_window: int, stall_window: int) -> str:
    if age_seconds is None:
        return "idle"
    if age_seconds <= progress_window:
        return "progressing"
    if age_seconds >= stall_window:
        return "stalled"
    return "idle"


def main() -> int:
    args = parse_args()
    project = args.project.strip()
    peer_id = args.peer_id.strip()
    peer_root = TASKS_ROOT / project / "peer-deliveries" / peer_id
    files = _candidate_files(peer_root, args.task_id.strip() if args.task_id else None)
    latest_mtime, latest_path = _latest_activity(files)

    now = datetime.now(timezone.utc).timestamp()
    age_seconds = None if latest_mtime is None else max(0.0, now - latest_mtime)
    state = _state_for_age(age_seconds, args.progress_window, args.stall_window)

    payload = {
        "project": project,
        "peer_id": peer_id,
        "state": state,
        "latest_age_seconds": None if age_seconds is None else round(age_seconds, 3),
        "latest_activity_at": None if latest_mtime is None else datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat(),
        "latest_path": None if latest_path is None else str(latest_path),
        "progress_window_seconds": args.progress_window,
        "stall_window_seconds": args.stall_window,
        "peer_root": str(peer_root),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return {"progressing": 0, "idle": 1, "stalled": 2}[state]


if __name__ == "__main__":
    raise SystemExit(main())
