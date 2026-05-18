"""events_watcher.py — C10 passive re-ingest of handoff JSONs into state.db.

Walks ``~/.agents/tasks/<project>/patrol/handoffs/*.json`` (one project's
slice via ``--project`` or all), derives an event row per handoff, and
inserts it into the state.db events table via ``record_event_if_new`` so
re-runs are idempotent.

Why: legacy/shell dispatch paths don't know about state.db. They still write
the handoff JSON. The watcher re-derives events from those files so the
events table gets full coverage — foundation for C11 subscribers
(feishu-announcer etc.).

Modes::

    events_watcher.py --once
    events_watcher.py --watch [--interval 30]
    events_watcher.py --dry-run
    events_watcher.py --project install

Fingerprint = sha1(project|task_id|kind|source|target)[:16] — stable across
runs so re-ingest skips already-recorded events.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.lib.state import open_db, record_event_if_new  # noqa: E402

try:
    from core.lib.real_home import real_user_home  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    _LIB = _REPO_ROOT / "core" / "lib"
    if str(_LIB) not in sys.path:
        sys.path.insert(0, str(_LIB))
    from real_home import real_user_home  # type: ignore[no-redef]

log = logging.getLogger("events_watcher")


# ---------------------------------------------------------------------------
# Event derivation
# ---------------------------------------------------------------------------

_KIND_TO_TYPE: dict[str, str] = {
    "dispatch": "task.dispatched",
    "completion": "task.completed",
    "learning": "patrol.learning",
    "notice": "seat.notified",
    "reminder": "seat.notified",
    "unblock": "seat.notified",
}


def derive_event(
    handoff: dict[str, Any],
    project: str,
) -> tuple[str, dict[str, Any], str]:
    """Return (event_type, payload, fingerprint) for a handoff dict.

    Unknown kinds produce event_type='handoff.unknown' with the raw handoff
    preserved as payload; callers should log a warning.
    """
    kind = str(handoff.get("kind", "") or "").strip()
    task_id = str(handoff.get("task_id", "") or "").strip()
    source = str(handoff.get("source", "") or "").strip()
    target = str(handoff.get("target", "") or "").strip()

    event_type = _KIND_TO_TYPE.get(kind, "handoff.unknown")

    if event_type == "task.dispatched":
        payload = {
            "task_id": task_id,
            "source": source,
            "target": target,
            "title": handoff.get("title"),
        }
    elif event_type == "task.completed":
        payload = {
            "task_id": task_id,
            "source": source,
            "target": target,
            "disposition": handoff.get("frontstage_disposition"),
        }
    elif event_type == "patrol.learning":
        payload = {
            "task_id": task_id,
            "source": source,
            "message": handoff.get("message"),
        }
    elif event_type == "seat.notified":
        payload = {
            "task_id": task_id,
            "source": source,
            "target": target,
            "kind": kind,
        }
    else:
        payload = {"raw": handoff}

    basis = "|".join([project, task_id, kind, source, target])
    fingerprint = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
    return event_type, payload, fingerprint


# ---------------------------------------------------------------------------
# Filesystem scan
# ---------------------------------------------------------------------------

def iter_handoffs(
    tasks_root: Path,
    project_filter: str | None = None,
) -> Iterable[tuple[str, Path]]:
    """Yield (project, handoff_path) pairs sorted by (project, filename).

    ``tasks_root`` should point to ``~/.agents/tasks`` (or a test fixture).
    """
    if not tasks_root.is_dir():
        return
    for project_dir in sorted(p for p in tasks_root.iterdir() if p.is_dir()):
        project = project_dir.name
        if project_filter is not None and project != project_filter:
            continue
        handoff_dir = project_dir / "patrol" / "handoffs"
        if not handoff_dir.is_dir():
            continue
        for handoff_path in sorted(handoff_dir.glob("*.json")):
            yield project, handoff_path


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def process_once(
    conn: sqlite3.Connection,
    tasks_root: Path,
    *,
    project_filter: str | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """One sweep: read handoffs, insert new events, return counts."""
    processed = written = skipped = malformed = unknown = 0

    for project, handoff_path in iter_handoffs(tasks_root, project_filter):
        processed += 1
        try:
            data = json.loads(handoff_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("events_watcher: skipping malformed %s: %s", handoff_path, exc)
            malformed += 1
            continue
        if not isinstance(data, dict):
            log.warning("events_watcher: skipping non-object JSON %s", handoff_path)
            malformed += 1
            continue

        event_type, payload, fingerprint = derive_event(data, project)
        if event_type == "handoff.unknown":
            log.warning(
                "events_watcher: unknown kind %r in %s — recording as handoff.unknown",
                data.get("kind"), handoff_path,
            )
            unknown += 1

        if dry_run:
            print(
                f"[dry-run] {project} {handoff_path.name} -> "
                f"type={event_type} fp={fingerprint}"
            )
            continue

        inserted = record_event_if_new(
            conn, event_type, project, fingerprint, **payload
        )
        if inserted:
            written += 1
        else:
            skipped += 1

    return {
        "processed": processed,
        "written": written,
        "skipped": skipped,
        "malformed": malformed,
        "unknown": unknown,
    }


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------

class _SigintExit:
    """SIGINT → set flag; main loop exits after current cycle."""

    def __init__(self) -> None:
        self.stop = False

    def __call__(self, *_: Any) -> None:
        self.stop = True


def run_watch(
    conn: sqlite3.Connection,
    tasks_root: Path,
    *,
    interval: float,
    project_filter: str | None,
    dry_run: bool,
) -> int:
    stop = _SigintExit()
    signal.signal(signal.SIGINT, stop)
    cycle = 0
    total_written = 0
    while not stop.stop:
        cycle += 1
        counts = process_once(
            conn, tasks_root,
            project_filter=project_filter, dry_run=dry_run,
        )
        total_written += counts["written"]
        print(
            f"watcher: cycle {cycle} processed={counts['processed']} "
            f"written={counts['written']} skipped={counts['skipped']}"
        )
        sys.stdout.flush()
        # Interruptible sleep: 0.5s granularity so SIGINT fires within half a second.
        deadline = time.monotonic() + interval
        while not stop.stop and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
    print(f"watcher: stopped, total written={total_written}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="events_watcher.py",
        description=(
            "C10 passive watcher: re-derive events from ~/.agents/tasks/"
            "*/patrol/handoffs/*.json into state.db."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true",
        help="Process all pending handoffs once and exit (default).",
    )
    mode.add_argument(
        "--watch", action="store_true",
        help="Loop, polling every --interval seconds until SIGINT.",
    )
    parser.add_argument(
        "--interval", type=float, default=30.0,
        help="Polling interval in seconds for --watch (default: 30).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned inserts; do not write to state.db.",
    )
    parser.add_argument(
        "--project", default=None,
        help="Restrict to a single project directory name.",
    )
    parser.add_argument(
        "--tasks-root", default=None,
        help="Override ~/.agents/tasks root (primarily for tests).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)

    tasks_root = (
        Path(args.tasks_root).expanduser().resolve()
        if args.tasks_root
        else real_user_home() / ".agents" / "tasks"
    )

    conn = open_db()
    try:
        if args.watch:
            return run_watch(
                conn, tasks_root,
                interval=max(1.0, args.interval),
                project_filter=args.project,
                dry_run=args.dry_run,
            )
        counts = process_once(
            conn, tasks_root,
            project_filter=args.project, dry_run=args.dry_run,
        )
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}watcher: processed={counts['processed']} "
            f"written={counts['written']} skipped={counts['skipped']} "
            f"malformed={counts['malformed']} unknown={counts['unknown']}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
