#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import (
    extract_canonical_verdict,
    find_consumed_ack,
    handoff_assigned,
    load_json,
    load_profile,
)


VALID_VERDICTS = {
    "APPROVED",
    "APPROVED_WITH_NITS",
    "CHANGES_REQUESTED",
    "BLOCKED",
    "DECISION_NEEDED",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a harness handoff state.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--task-id", required=True, help="Task id.")
    parser.add_argument("--source", required=True, help="Source seat.")
    parser.add_argument("--target", required=True, help="Target seat.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    receipt_path = profile.handoff_path(args.task_id, args.source, args.target)
    receipt = load_json(receipt_path) or {}
    todo_path = profile.todo_path(args.target)
    delivery_path = Path(str(receipt.get("delivery_path", "")).strip()) if receipt.get("delivery_path") else profile.delivery_path(args.source)
    assigned = handoff_assigned(
        profile,
        task_id=args.task_id,
        source=args.source,
        target=args.target,
        kind=str(receipt.get("kind", "dispatch")),
        delivery_path=str(receipt.get("delivery_path", "")),
    )
    notified = bool(receipt.get("notified_at"))
    ack_line = find_consumed_ack(todo_path, task_id=args.task_id, source=args.source)
    consumed = bool(ack_line)
    verdict = extract_canonical_verdict(delivery_path) if delivery_path.exists() else None
    verdict_valid = True
    source_role = profile.seat_roles.get(args.source, "")
    if receipt.get("kind") == "completion" and source_role == "reviewer":
        verdict_valid = verdict in VALID_VERDICTS
    payload = {
        "task_id": args.task_id,
        "source": args.source,
        "target": args.target,
        "assigned": assigned,
        "notified": notified,
        "consumed": consumed,
        "verdict": verdict,
        "verdict_valid": verdict_valid,
        "receipt_path": str(receipt_path),
        "todo_path": str(todo_path),
        "delivery_path": str(delivery_path),
        "consumed_ack": ack_line,
        "healthy": assigned and notified and consumed and verdict_valid,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"task: {args.task_id}")
        print(f"source: {args.source}")
        print(f"target: {args.target}")
        print(f"assigned: {assigned}")
        print(f"notified: {notified}")
        print(f"consumed: {consumed}")
        if verdict is not None:
            print(f"verdict: {verdict}")
            print(f"verdict_valid: {verdict_valid}")
        if ack_line:
            print(f"ack: {ack_line}")
        print(f"healthy: {payload['healthy']}")
    return 0 if payload["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
