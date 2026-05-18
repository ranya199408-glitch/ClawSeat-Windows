#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import (
    HarnessProfile,
    executable_command,
    find_consumed_ack,
    handoff_assigned,
    heartbeat_state,
    load_json,
    load_profile,
    materialize_profile_runtime,
    run_command,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the CLI control console for a harness profile.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args()


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def seat_sets(profile: HarnessProfile) -> dict[str, list[str]]:
    roster = _unique_ordered(list(profile.seats))
    materialized = _unique_ordered(list(getattr(profile, "materialized_seats", None) or roster))
    runtime = _unique_ordered(list(getattr(profile, "runtime_seats", None) or materialized))
    bootstrap = _unique_ordered(list(profile.bootstrap_seats or []))
    default_start = _unique_ordered(list(profile.default_start_seats or bootstrap or materialized))
    backend = [seat for seat in runtime if seat != profile.heartbeat_owner]
    return {
        "roster": roster,
        "materialized": materialized,
        "runtime": runtime,
        "bootstrap": bootstrap,
        "default_start": default_start,
        "backend": backend,
    }


def seat_summary(profile: HarnessProfile) -> list[dict[str, str]]:
    result = run_command(executable_command(profile.status_script), cwd=profile.repo_root)
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    rows: list[dict[str, str]] = []
    seen_seats: set[str] = set()
    heartbeat = heartbeat_state(profile, profile.heartbeat_owner)
    heartbeat_status = {
        "verified": "HEARTBEAT_CONFIGURED",
        "unverified": "HEARTBEAT_UNVERIFIED",
        "missing": "HEARTBEAT_PENDING",
    }[str(heartbeat["state"])]
    rows.append(
        {
            "seat": profile.heartbeat_owner,
            "role": profile.seat_roles.get(profile.heartbeat_owner, ""),
            "status": heartbeat_status,
        }
    )
    seen_seats.add(profile.heartbeat_owner)
    for line in lines:
        if ":" not in line:
            continue
        seat, rest = line.split(":", 1)
        seat_id = seat.strip()
        status = rest.strip()
        if seat_id == profile.heartbeat_owner:
            rows[0]["status"] = f"{rows[0]['status']}; {status}"
            seen_seats.add(seat_id)
            continue
        rows.append({"seat": seat_id, "role": profile.seat_roles.get(seat_id, ""), "status": status})
        seen_seats.add(seat_id)
    for seat in profile.seats:
        if seat in seen_seats:
            continue
        role = profile.seat_roles.get(seat, "")
        status = "no status"
        if role:
            status = f"{role}; no status"
        rows.append({"seat": seat, "role": role, "status": status})
    return rows


def handoff_summary(profile: HarnessProfile) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    handoff_dir = profile.handoff_dir
    if not handoff_dir.exists():
        return items
    for path in sorted(handoff_dir.glob("*.json")):
        payload = load_json(path) or {}
        target = str(payload.get("target", ""))
        source = str(payload.get("source", ""))
        task_id = str(payload.get("task_id", ""))
        todo_path = profile.todo_path(target)
        assigned = handoff_assigned(
            profile,
            task_id=task_id,
            source=source,
            target=target,
            kind=str(payload.get("kind", "dispatch")),
            delivery_path=str(payload.get("delivery_path", "")),
        )
        items.append(
            {
                "task_id": task_id,
                "source": source,
                "target": target,
                "kind": payload.get("kind", "dispatch"),
                "assigned": assigned,
                "notified": bool(payload.get("notified_at")),
                "consumed": bool(payload.get("consumed_at")) or bool(find_consumed_ack(todo_path, task_id=task_id, source=source)),
                "receipt": str(path),
            }
        )
    return items


def heartbeat_summary(profile: HarnessProfile) -> dict[str, object]:
    return heartbeat_state(profile, profile.heartbeat_owner)


def reminder_summary(profile: HarnessProfile) -> str:
    result = run_command(executable_command(profile.patrol_script), cwd=profile.repo_root)
    return (result.stdout or result.stderr).strip()


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    materialize_profile_runtime(profile)
    payload = {
        "profile": profile.profile_name,
        "active_loop_owner": profile.active_loop_owner,
        "heartbeat_owner": profile.heartbeat_owner,
        "seat_sets": seat_sets(profile),
        "seats": seat_summary(profile),
        "handoffs": handoff_summary(profile),
        "heartbeat": heartbeat_summary(profile),
        "reminders": reminder_summary(profile),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"profile: {profile.profile_name}")
    print(f"active loop owner: {profile.active_loop_owner}")
    print(f"heartbeat owner: {profile.heartbeat_owner}")
    print("\n== Seat Sets ==")
    for label, items in payload["seat_sets"].items():
        rendered = ", ".join(items) if items else "(none)"
        print(f"- {label}: {rendered}")
    print("\n== Seats ==")
    for seat in payload["seats"]:
        print(f"- {seat['seat']}: {seat['status']}")
    print("\n== Handoffs ==")
    if not payload["handoffs"]:
        print("- none")
    else:
        for item in payload["handoffs"]:
            print(
                f"- {item['task_id']} {item['source']} -> {item['target']}: "
                f"assigned={item['assigned']} notified={item['notified']} consumed={item['consumed']}"
            )
    print("\n== Heartbeat ==")
    print(f"- configured: {payload['heartbeat']['configured']}")
    print(f"- receipt: {profile.heartbeat_receipt}")
    print("\n== Reminder candidates ==")
    print(payload["reminders"] or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
