#!/usr/bin/env python3
"""state-admin — operator CLI for the C8 state.db ledger.

Usage::

    state-admin seed                            # seed from filesystem artefacts
    state-admin show-seats [--project X]        # list seats
    state-admin show-tasks [--project X] [--status open]
    state-admin pick --project X --role ROLE    # least-busy live seat
    state-admin recent-events [--limit 20]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.lib.state import (  # noqa: E402
    open_db,
    list_projects,
    list_seats,
    get_task,
    pick_least_busy_seat,
    seed_from_filesystem,
)

try:
    import sqlite3 as _sqlite3
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_seed(args: argparse.Namespace) -> int:
    conn = open_db()
    counts = seed_from_filesystem(conn=conn)
    print(
        f"Seeded: {counts['projects']} project(s), "
        f"{counts['seats']} seat(s), "
        f"{counts['tasks']} task(s)"
    )
    return 0


def cmd_show_seats(args: argparse.Namespace) -> int:
    conn = open_db()
    projects = (
        [args.project]
        if args.project
        else [p.name for p in list_projects(conn)]
    )
    total = 0
    for proj in projects:
        seats = list_seats(conn, proj)
        if not seats:
            continue
        print(f"\n{'─'*60}")
        print(f"  project: {proj}")
        print(f"{'─'*60}")
        header = f"  {'seat_id':<28} {'role':<28} {'status':<10} {'tool':<8} {'auth_mode'}"
        print(header)
        print(f"  {'─'*24} {'─'*24} {'─'*8} {'─'*6} {'─'*10}")
        for s in seats:
            print(
                f"  {s.seat_id:<28} {s.role:<28} {s.status:<10} "
                f"{s.tool:<8} {s.auth_mode}"
            )
            total += 1
    print(f"\n{total} seat(s) total.")
    return 0


def cmd_show_tasks(args: argparse.Namespace) -> int:
    conn = open_db()
    projects = (
        [args.project]
        if args.project
        else [p.name for p in list_projects(conn)]
    )
    status_filter = None
    if args.status == "open":
        status_filter = ("dispatched", "in_progress")

    total = 0
    for proj in projects:
        q = "SELECT * FROM tasks WHERE project = ?"
        params: list = [proj]
        if status_filter:
            placeholders = ",".join("?" for _ in status_filter)
            q += f" AND status IN ({placeholders})"
            params.extend(status_filter)
        q += " ORDER BY opened_at DESC"
        rows = conn.execute(q, params).fetchall()
        if not rows:
            continue
        print(f"\n{'─'*60}")
        print(f"  project: {proj}")
        print(f"{'─'*60}")
        header = f"  {'id':<32} {'status':<12} {'target':<20} {'opened_at'}"
        print(header)
        print(f"  {'─'*28} {'─'*10} {'─'*18} {'─'*24}")
        for r in rows:
            print(
                f"  {r['id']:<32} {r['status']:<12} "
                f"{r['target']:<20} {r['opened_at']}"
            )
            total += 1
    print(f"\n{total} task(s) shown.")
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    conn = open_db()
    seat = pick_least_busy_seat(conn, args.project, args.role)
    if seat is None:
        print(
            f"No live seat found for project={args.project!r} role={args.role!r}"
        )
        return 1
    print(
        f"Least-busy seat: {seat.seat_id}  "
        f"(role={seat.role}, status={seat.status}, tool={seat.tool})"
    )
    return 0


def cmd_recent_events(args: argparse.Namespace) -> int:
    conn = open_db()
    limit = max(1, args.limit)
    rows = conn.execute(
        "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    if not rows:
        print("No events recorded.")
        return 0
    header = f"  {'ts':<28} {'type':<30} {'project':<16} payload"
    print(header)
    print(f"  {'─'*26} {'─'*28} {'─'*14} {'─'*30}")
    for r in rows:
        payload_preview = r["payload_json"][:60]
        project_col = r["project"] or ""
        print(
            f"  {r['ts']:<28} {r['type']:<30} "
            f"{project_col:<16} {payload_preview}"
        )
    print(f"\n{len(rows)} event(s) shown.")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="state-admin",
        description="Operator CLI for the ClawSeat state.db ledger (C8).",
    )
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # seed
    sub.add_parser("seed", help="Seed DB from filesystem artefacts (idempotent).")

    # show-seats
    sp = sub.add_parser("show-seats", help="List seats.")
    sp.add_argument("--project", metavar="PROJECT", default="")

    # show-tasks
    sp = sub.add_parser("show-tasks", help="List tasks.")
    sp.add_argument("--project", metavar="PROJECT", default="")
    sp.add_argument(
        "--status",
        metavar="STATUS",
        default="",
        help="Filter by status. Use 'open' for dispatched+in_progress.",
    )

    # pick
    sp = sub.add_parser("pick", help="Pick least-busy live seat.")
    sp.add_argument("--project", required=True, metavar="PROJECT")
    sp.add_argument("--role", required=True, metavar="ROLE")

    # recent-events
    sp = sub.add_parser("recent-events", help="Show recent events.")
    sp.add_argument("--limit", type=int, default=20, metavar="N")

    return p


_COMMANDS = {
    "seed": cmd_seed,
    "show-seats": cmd_show_seats,
    "show-tasks": cmd_show_tasks,
    "pick": cmd_pick,
    "recent-events": cmd_recent_events,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
