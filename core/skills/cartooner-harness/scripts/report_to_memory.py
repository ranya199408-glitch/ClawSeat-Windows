#!/usr/bin/env python3
"""report_to_memory.py — Mandatory user-direct reporting contract.

Any seat that receives a user-direct instruction MUST call this before /
during / after execution. Fail-closed: if this exits non-zero, the seat
must abort the user-direct action.

See `references/user-direct-contract.md` for the full contract.

Side effects
------------
- Validates payload shape
- Marks supersession on a prior lane (if --supersedes given)
- Appends generation_log entry (event = <args.event>, actor = <triggered_by>)
- If automation_mode == "auto" AND triggered_by == "user", flips mode to
  "manual" and records the flip reason (escalation trigger
  user_direct_received)

Exit
----
- 0 on success
- non-zero on validation failure (fail-closed)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_EVENTS = (
    "user_direct_request",
    "lane_completed",
    "shot_list_authored",
    "shot_list_revised",
    "subagent_started",
    "subagent_completed",
    "subagent_failed",
    # audit finding #1 (2026-05-11): memory needs a sanctioned channel
    # for internal coordination notes (anchor files written, receiver
    # notified via send-and-verify, brief drafted, etc.) — without it,
    # memory was bypassing the protocol and appending raw role/action
    # entries directly to generation_log.jsonl, breaking the schema
    # patrol depends on.
    "memory_internal_note",
)
VALID_TRIGGERS = ("user", "memory", "patrol")
VALID_SUBAGENT_TYPES = ("", "root_cause", "reference_learning")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="report_to_memory")
    p.add_argument("--project", required=True)
    p.add_argument("--event", required=True, choices=VALID_EVENTS)
    p.add_argument("--seat", required=True, choices=common.VALID_SEATS,
                   help="Seat that received the user-direct instruction (or that is reporting)")
    p.add_argument("--triggered-by", default="user", choices=VALID_TRIGGERS)
    p.add_argument("--intent", default="",
                   help="Free-form description of what the user requested")
    p.add_argument("--action", default="",
                   help="e.g. spawn_lane, spawn_subagent, deposit_asset, revise_shot_list")
    p.add_argument("--supersedes", default="",
                   help="Lane id this report supersedes (Producer-wins resolution)")
    p.add_argument("--child-lane", default="",
                   help="Lane id spawned as a result")
    p.add_argument("--subagent-type", default="", choices=VALID_SUBAGENT_TYPES)
    p.add_argument("--subagent-inputs", default="{}", help="JSON object")
    p.add_argument("--subagent-output-path", default="",
                   help="Path to subagent's text report (no images)")
    p.add_argument("--note", default="",
                   help="(memory_internal_note) free-form coordination note: "
                        "files anchored, receivers notified, briefs drafted, "
                        "or any other memory-internal action that doesn't "
                        "fit the typed events. Captured in generation_log so "
                        "patrol audit + producer review can see what memory did.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        subagent_inputs = json.loads(args.subagent_inputs)
    except json.JSONDecodeError as e:
        common.fail_closed(f"invalid --subagent-inputs JSON: {e}")

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)

    if args.supersedes:
        common.validate_id_token(args.supersedes, kind="--supersedes")
        prior = index.setdefault("lanes", {}).get(args.supersedes)
        if prior is None:
            common.fail_closed(f"--supersedes lane not found: {args.supersedes}")
        prior["state"] = "superseded"
        prior["superseded_at"] = common.now_iso()
        prior["superseded_by_event"] = args.event

        prior_file = common.load_lane(args.project, args.supersedes)
        if prior_file is not None:
            prior_file["state"] = "superseded"
            common.write_lane(args.project, args.supersedes, prior_file)

    auto_flipped = False
    if (
        args.triggered_by == "user"
        and args.event == "user_direct_request"
        and index.get("automation_mode") == "auto"
    ):
        index["automation_mode"] = "manual"
        index["automation_flipped_at"] = common.now_iso()
        index["automation_flipped_reason"] = "user_direct_received"
        auto_flipped = True

    # memory_internal_note requires --note (it's the entire payload)
    if args.event == "memory_internal_note" and not args.note.strip():
        common.fail_closed(
            "--note is required for --event memory_internal_note "
            "(this event is the sanctioned channel for memory's free-form "
            "coordination notes; an empty note defeats the purpose)"
        )

    common.write_project_index(args.project, index)

    common.append_generation_log(args.project, {
        "event": args.event,
        "actor": args.triggered_by,
        "triggered_by": args.triggered_by,
        "seat": args.seat,
        "intent": args.intent,
        "action": args.action,
        "supersedes": args.supersedes or None,
        "child_lane": args.child_lane or None,
        "subagent_type": args.subagent_type or None,
        "subagent_inputs": subagent_inputs or None,
        "subagent_output_path": args.subagent_output_path or None,
        "auto_to_manual_flip": auto_flipped or None,
        "note": args.note or None,
    })

    return 0


if __name__ == "__main__":
    sys.exit(main())
