#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add core/lib to path so seat_resolver can be imported
_scripts_dir = Path(__file__).parent.resolve()
_core_lib = _scripts_dir.parent.parent.parent / "lib"
if str(_core_lib) not in sys.path:
    sys.path.insert(0, str(_core_lib))

from _common import (
    assert_target_not_memory,
    build_notify_payload,
    load_profile,
    notify,
    require_success,
    send_feishu_user_message,
    stable_dispatch_nonce,
    utc_now_iso,
    write_json,
)

from seat_resolver import resolve_seat_from_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a protocol-compliant seat notification.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--source", required=True, help="Seat sending the notification.")
    parser.add_argument("--target", required=True, help="Seat receiving the notification.")
    parser.add_argument("--message", required=True, help="Human-readable message body.")
    parser.add_argument("--task-id", help="Optional task id for receipt tracking.")
    parser.add_argument("--reply-to", help="Optional reply target to mention in the notice.")
    parser.add_argument(
        "--kind",
        default="notice",
        help="Notification kind for receipt metadata (notice, reminder, unblock, etc).",
    )
    parser.add_argument(
        "--skip-receipt",
        action="store_true",
        help="Do not write a JSON receipt even when task-id is provided.",
    )
    parser.add_argument(
        "--allow-notify-failure",
        action="store_true",
        help=(
            "Continue even if tmux notify fails (exit 0). "
            "Default: exit 1 with a NOTIFY FAILED banner. "
            "Use in CI/batch where notify is best-effort."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # T22 fold-in (from upstream): notify_seat.py is allowed to target
    # memory because T7 memory-query-protocol Missing-Key Escalation
    # requires it — memory needs to receive notification when a key it
    # asked for is missing. dispatch_task.py + dynamic variants remain
    # blocked by assert_target_not_memory. We still call the guard for
    # non-memory targets so the caller_tool-scoped exemption is explicit.
    assert_target_not_memory(args.target, "notify_seat.py")
    profile = load_profile(args.profile)
    # H2 (PR #1): shared payload builder, replacing the local build_payload
    # fork that drifted from notify_seat_dynamic.py.
    payload = build_notify_payload(
        source=args.source,
        target=args.target,
        message=args.message,
        kind=args.kind,
        task_id=args.task_id,
        reply_to=args.reply_to,
    )
    # T19 (from upstream): route via seat_resolver — tmux seats get notify(),
    # openclaw seats get the feishu-user broadcast, file-only targets write
    # a receipt with a stderr warning.
    resolution = resolve_seat_from_profile(args.target, profile)

    if resolution.kind == "tmux":
        result = notify(profile, args.target, payload)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            print("============ NOTIFY FAILED ============", file=sys.stderr)
            print(f"  target : {args.target}", file=sys.stderr)
            print(f"  reason : {detail}", file=sys.stderr)
            print(
                f"  fix    : send-and-verify.sh --project {profile.project_name} "
                f"{args.target} '<message>'",
                file=sys.stderr,
            )
            print("=======================================", file=sys.stderr)
            if not getattr(args, "allow_notify_failure", False):
                raise SystemExit(1)
            print("warn: --allow-notify-failure set; continuing", file=sys.stderr)
    elif resolution.kind == "openclaw":
        broadcast = send_feishu_user_message(payload, project=profile.project_name)
        if broadcast.get("status") == "failed":
            detail = broadcast.get("stderr") or broadcast.get("stdout") or broadcast.get("reason", "unknown")
            raise SystemExit(f"notify seat (feishu) failed for {args.target}: {detail}")
    else:
        # kind=file-only: no known transport — write receipt only with a warning.
        print(
            f"warn: notify target {args.target!r} resolves to kind=file-only — "
            "no transport available. Receipt written but seat not notified.",
            file=sys.stderr,
        )

    if args.task_id and not args.skip_receipt:
        receipt = {
            "kind": args.kind,
            "task_id": args.task_id,
            "source": args.source,
            "target": args.target,
            "reply_to": args.reply_to,
            "message": payload,
            "notified_at": utc_now_iso(),
            "transport": resolution.transport,
        }
        receipt_path = profile.handoff_path(args.task_id, args.source, args.target)
        write_json(receipt_path, receipt)
        print(f"receipt: {receipt_path}")

    print(f"notified {args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
