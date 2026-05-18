#!/usr/bin/env python3
"""escalate_to_producer.py — Record an escalation from auto mode to user.

Used in auto mode when memory hits a decision wall it cannot resolve
(no qualifying auto-pick winner, lane failure, SLA breach, ambiguous
feedback, etc.). Records the escalation and optionally flips automation
back to manual so the next pick_winner / iterate call blocks on user.

Effect
------
- Writes escalations/<escalation-id>.toml
- Records escalation in PROJECT_INDEX.escalations
- Appends generation_log (event=escalate_to_producer)
- If --auto-flip-to-manual: also updates PROJECT_INDEX.automation_mode = manual
- Prints escalation_id to stdout

Triggers
--------
See set_automation_mode.VALID_ESCALATE_TRIGGERS.

Caller flow (memory in auto mode)
---------------------------------
1. memory detects the trigger (e.g. pick_winner exits non-zero with
   "no qualifying winner")
2. memory subprocess.run(escalate_to_producer.py --trigger ...
   --auto-flip-to-manual ...)
3. memory's next pick_winner / iterate / dispatch call blocks on user
   (manual mode now in effect)

Exit
----
- 0 on success
- non-zero on validation failure (fail-closed)
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_TRIGGERS = (
    "lane_failure",
    "sla_breach",
    "phase_transition",
    "budget_exhausted",
    "tournament_ready_no_auto_pick_strategy",
    "user_direct_received",
    "seat_authorization_violation",
    "vision_spec_violation",
    "subagent_failure",
    "feedback_unclear",
    "custom",
)
VALID_ACTORS = ("memory_acting_director", "patrol")
VALID_STATUSES = ("open", "resolved", "abandoned")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="escalate_to_producer")
    p.add_argument("--project", required=True)
    p.add_argument("--trigger", required=True, choices=VALID_TRIGGERS)
    p.add_argument("--actor", default="memory_acting_director", choices=VALID_ACTORS)
    p.add_argument("--context", default="",
                   help="Free-form context describing the wall hit (e.g. round_id, lane_id, "
                        "feedback excerpt, error class)")
    p.add_argument("--parent-lane", default="")
    p.add_argument("--parent-shot", default="")
    p.add_argument("--parent-round", default="",
                   help="Tournament round_id when trigger=tournament_ready_no_auto_pick_strategy")
    p.add_argument("--auto-flip-to-manual", action="store_true",
                   help="Flip automation_mode back to manual atomically with the escalation")
    return p.parse_args(argv)


def make_escalation_id() -> str:
    return f"esc-{secrets.token_hex(4)}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)

    if args.parent_lane:
        common.validate_id_token(args.parent_lane, kind="--parent-lane")
        if args.parent_lane not in index.get("lanes", {}):
            common.fail_closed(
                f"--parent-lane not in PROJECT_INDEX.lanes: {args.parent_lane}"
            )
    if args.parent_round:
        common.validate_id_token(args.parent_round, kind="--parent-round")
        if args.parent_round not in index.get("tournaments", {}):
            common.fail_closed(
                f"--parent-round not in PROJECT_INDEX.tournaments: {args.parent_round}"
            )

    escalation_id = make_escalation_id()
    now = common.now_iso()
    prev_mode = index.get("automation_mode", "manual")

    record: dict = {
        "id": escalation_id,
        "trigger": args.trigger,
        "actor": args.actor,
        "context": args.context,
        "parent_lane": args.parent_lane,
        "parent_shot": args.parent_shot,
        "parent_round": args.parent_round,
        "created_at": now,
        "status": "open",
        "mode_at_escalation": prev_mode,
    }

    esc_dir = common.project_root(args.project) / "escalations"
    esc_dir.mkdir(parents=True, exist_ok=True)
    esc_path = esc_dir / f"{escalation_id}.toml"
    esc_path.write_text(common.serialize_toml(record), encoding="utf-8")

    index.setdefault("escalations", {})[escalation_id] = record

    flipped = False
    if args.auto_flip_to_manual and prev_mode != "manual":
        index["automation_mode"] = "manual"
        index["automation_config"] = {
            "mode": "manual",
            "set_at": now,
            "set_by": args.actor,
            "triggered_by": f"escalate_to_producer:{args.trigger}",
        }
        flipped = True

    common.write_project_index(args.project, index)

    common.append_generation_log(args.project, {
        "event": "escalate_to_producer",
        "escalation_id": escalation_id,
        "trigger": args.trigger,
        "actor": args.actor,
        "context": args.context or None,
        "parent_lane": args.parent_lane or None,
        "parent_shot": args.parent_shot or None,
        "parent_round": args.parent_round or None,
        "auto_flipped_to_manual": flipped,
        "previous_mode": prev_mode if flipped else None,
    })

    print(escalation_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
