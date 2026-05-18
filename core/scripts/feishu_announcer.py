"""feishu_announcer.py — C11 first subscriber on the state.db events bus.

Reads events with type in ('task.completed', 'chain.closeout') where
feishu_sent IS NULL, builds Feishu delegation-report envelopes, and sends
them via _feishu.send_feishu_user_message. Sets feishu_sent timestamp on
success; leaves NULL for retry on failure.

Modes::

    feishu_announcer.py --once                   # process all pending, exit
    feishu_announcer.py --watch [--interval 60]  # loop until SIGINT
    feishu_announcer.py --dry-run                # print envelopes, do not send
    feishu_announcer.py --project install        # scope to one project
    feishu_announcer.py --types task.completed,chain.closeout
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_HARNESS_SCRIPTS = _REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts"
if str(_HARNESS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_HARNESS_SCRIPTS))

from core.lib.state import (  # noqa: E402
    Event,
    list_unsent_feishu_events,
    mark_feishu_sent,
    open_db,
)
from core.lib.state import _utcnow  # noqa: E402  (private, same package)

import _feishu  # noqa: E402

# Expose the function at module level so tests can patch it cleanly.
send_feishu_user_message = _feishu.send_feishu_user_message

log = logging.getLogger("feishu_announcer")

_DEFAULT_EVENT_TYPES = ("task.completed", "chain.closeout", "seat.blocked_on_modal", "seat.context_near_limit")


# ---------------------------------------------------------------------------
# Pure derivation helpers (no side effects — trivially testable)
# ---------------------------------------------------------------------------

def _derive_lane(payload: dict[str, Any]) -> str:
    """Return the lane string; validated against VALID_DELEGATION_LANES."""
    raw = str(payload.get("lane") or "planning").strip().lower()
    if raw in _feishu.VALID_DELEGATION_LANES:
        return raw
    return "planning"


def _derive_report_status(event_type: str, payload: dict[str, Any]) -> str:
    if event_type in ("task.completed", "chain.closeout"):
        return "done"
    return "in_progress"


def _derive_decision_hint(payload: dict[str, Any]) -> str:
    disp = (payload.get("disposition") or "").strip().upper()
    if disp == "USER_DECISION_NEEDED":
        return "ask_user"
    if disp == "AUTO_ADVANCE":
        return "proceed"
    return "proceed"


def _derive_user_gate(payload: dict[str, Any]) -> str:
    disp = (payload.get("disposition") or "").strip().upper()
    return "required" if disp == "USER_DECISION_NEEDED" else "none"


def _derive_next_action(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "task.completed":
        return "consume_closeout"
    if event_type == "chain.closeout":
        return "finalize_chain"
    return "wait"


def _derive_summary(event_type: str, payload: dict[str, Any]) -> str:
    task_id = payload.get("task_id") or "?"
    source = payload.get("source") or "?"
    target = payload.get("target") or "?"
    if event_type == "task.completed":
        return f"{task_id} completed by {source} -> {target}"
    if event_type == "chain.closeout":
        return f"{task_id} chain closeout from {source}"
    return f"{task_id} event {event_type}"


# ---------------------------------------------------------------------------
# Envelope builder
# ---------------------------------------------------------------------------

def build_envelope(event: Event) -> str:
    """Build a Feishu delegation-report string for the given event."""
    payload: dict[str, Any] = json.loads(event.payload_json)
    project = event.project or "unknown"
    lane = _derive_lane(payload)
    task_id = payload.get("task_id") or "?"
    return _feishu.build_delegation_report_text(
        project=project,
        lane=lane,
        task_id=task_id,
        dispatch_nonce=_feishu.stable_dispatch_nonce(project, lane, task_id),
        report_status=_derive_report_status(event.type, payload),
        decision_hint=_derive_decision_hint(payload),
        user_gate=_derive_user_gate(payload),
        next_action=_derive_next_action(event.type, payload),
        summary=_derive_summary(event.type, payload),
        human_summary=payload.get("human_summary"),
    )


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_once(
    *,
    event_types: tuple[str, ...] = _DEFAULT_EVENT_TYPES,
    project_filter: str | None = None,
    dry_run: bool = False,
    conn=None,
    db_path: Path | None = None,
) -> dict[str, int]:
    """Process all pending events once. Returns summary counts."""
    if conn is None:
        conn = open_db(db_path)

    pending = list_unsent_feishu_events(
        conn,
        event_types=event_types,
        project=project_filter,
    )

    sent = failed = skipped = 0

    for event in pending:
        try:
            envelope = build_envelope(event)
        except Exception as exc:
            log.warning("announcer: envelope build failed for event %s: %s", event.id, exc)
            failed += 1
            continue

        if dry_run:
            print(f"[dry-run] event {event.id} type={event.type} project={event.project}")
            print(envelope)
            print()
            skipped += 1
            continue

        try:
            result = send_feishu_user_message(
                envelope, project=event.project, pre_check_auth=False
            )
        except Exception as exc:
            log.warning(
                "announcer: send raised for event %s: %s — will retry", event.id, exc
            )
            failed += 1
            continue

        status = (result or {}).get("status", "")
        if status == "sent":
            mark_feishu_sent(conn, event.id, _utcnow())
            sent += 1
        elif status == "failed":
            reason = (result or {}).get("reason") or (result or {}).get("stderr") or "unknown"
            print(
                f"announcer: send failed for event {event.id}: {reason} — will retry",
                file=sys.stderr,
            )
            failed += 1
        else:
            # skipped / needs_refresh / etc — leave NULL for retry
            failed += 1

    retrying = failed
    return {
        "pending": len(pending),
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "retrying": retrying,
    }


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------

class _SigintExit:
    def __init__(self) -> None:
        self.stop = False

    def __call__(self, *_: Any) -> None:
        self.stop = True


def run_watch(
    *,
    interval: float,
    event_types: tuple[str, ...],
    project_filter: str | None,
    dry_run: bool,
    db_path: Path | None = None,
) -> int:
    stop = _SigintExit()
    signal.signal(signal.SIGINT, stop)
    conn = open_db(db_path)
    cycle = 0
    total_sent = 0
    try:
        while not stop.stop:
            cycle += 1
            counts = process_once(
                event_types=event_types,
                project_filter=project_filter,
                dry_run=dry_run,
                conn=conn,
            )
            total_sent += counts["sent"]
            print(
                f"announcer: cycle {cycle} pending={counts['pending']} "
                f"sent={counts['sent']} failed={counts['failed']} "
                f"retrying={counts['retrying']}"
            )
            sys.stdout.flush()
            deadline = time.monotonic() + interval
            while not stop.stop and time.monotonic() < deadline:
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
    finally:
        conn.close()
    print(f"announcer: stopped, total sent={total_sent}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feishu_announcer.py",
        description=(
            "C11 feishu-announcer: send Feishu envelopes for unsent events "
            "in state.db."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true",
        help="Process all pending events once and exit (default mode).",
    )
    mode.add_argument(
        "--watch", action="store_true",
        help="Loop, polling every --interval seconds until SIGINT.",
    )
    parser.add_argument(
        "--interval", type=float, default=60.0,
        help="Polling interval in seconds for --watch (default: 60).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print envelopes; do not send or update feishu_sent.",
    )
    parser.add_argument(
        "--project", default=None,
        help="Restrict to a single project.",
    )
    parser.add_argument(
        "--types", default=None,
        help=(
            "Comma-separated event types to process "
            "(default: task.completed,chain.closeout)."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)

    event_types: tuple[str, ...] = _DEFAULT_EVENT_TYPES
    if args.types:
        event_types = tuple(t.strip() for t in args.types.split(",") if t.strip())

    if args.watch:
        return run_watch(
            interval=max(1.0, args.interval),
            event_types=event_types,
            project_filter=args.project,
            dry_run=args.dry_run,
        )

    try:
        conn = open_db()
    except Exception as exc:
        print(f"announcer: failed to open state.db: {exc}", file=sys.stderr)
        return 1

    try:
        counts = process_once(
            event_types=event_types,
            project_filter=args.project,
            dry_run=args.dry_run,
            conn=conn,
        )
        if counts["pending"] == 0:
            print("announcer: no pending events")
        else:
            prefix = "[dry-run] " if args.dry_run else ""
            print(
                f"{prefix}announcer: cycle 1 pending={counts['pending']} "
                f"sent={counts['sent']} failed={counts['failed']} "
                f"retrying={counts['retrying']}"
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
