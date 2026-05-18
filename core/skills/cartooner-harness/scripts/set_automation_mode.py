#!/usr/bin/env python3
"""set_automation_mode.py — Toggle project automation mode.

Effect
------
- Updates PROJECT_INDEX.automation_mode (manual / auto)
- Updates PROJECT_INDEX.automation_config (pick_strategy + escalate_on triggers)
- Appends generation_log (event=set_automation_mode)
- Prints new mode to stdout

Manual is the default. Auto requires explicit --pick-strategy because the
default escalate-always strategy needs no auto pick logic; choosing auto
without specifying intent is almost always a mistake.

Modes
-----
- manual: memory blocks on user input for every aesthetic decision
- auto:   memory may auto-pick per pick_strategy; escalates on triggers

escalate_on triggers (comma-separated):
- lane_failure
- sla_breach
- phase_transition
- budget_exhausted
- tournament_ready_no_auto_pick_strategy (default fallback when no
  qualifying auto-pick winner)
- user_direct_received (auto-flips back to manual)
- seat_authorization_violation

Exit
----
- 0 on success
- non-zero on validation failure (fail-closed)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_MODES = ("manual", "auto")
VALID_ACTORS = ("user", "memory_acting_director")
VALID_PICK_STRATEGIES = (
    "escalate-always",
    "model-metadata-rank",
    "first-passing",
    "random-from-passing",
)
VALID_ESCALATE_TRIGGERS = (
    "lane_failure",
    "sla_breach",
    "phase_transition",
    "budget_exhausted",
    "tournament_ready_no_auto_pick_strategy",
    "user_direct_received",
    "seat_authorization_violation",
    "vision_spec_violation",
    "subagent_failure",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="set_automation_mode")
    p.add_argument("--project", required=True)
    p.add_argument("--mode", required=True, choices=VALID_MODES)
    p.add_argument("--actor", default="user", choices=VALID_ACTORS)
    p.add_argument("--pick-strategy", default="",
                   help="(auto only) pick_winner strategy when memory acts as auto picker")
    p.add_argument("--escalate-on", default="",
                   help="(auto only) comma-separated triggers")
    p.add_argument("--triggered-by", default="",
                   help="Free-form reason for the mode change "
                        "(e.g. 'user_request', 'escalation', 'phase_transition')")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.mode == "auto":
        if not args.pick_strategy:
            common.fail_closed(
                "--mode auto requires --pick-strategy "
                "(escalate-always | model-metadata-rank | first-passing | random-from-passing)"
            )
        if args.pick_strategy not in VALID_PICK_STRATEGIES:
            common.fail_closed(
                f"--pick-strategy {args.pick_strategy!r} not in {VALID_PICK_STRATEGIES}"
            )
        if args.actor != "user":
            common.fail_closed(
                "--mode auto can only be set by --actor user "
                "(memory cannot self-elevate to auto mode)"
            )

    triggers: list[str] = []
    if args.escalate_on.strip():
        for t in args.escalate_on.split(","):
            tt = t.strip()
            if not tt:
                continue
            if tt not in VALID_ESCALATE_TRIGGERS:
                common.fail_closed(
                    f"unknown escalate trigger: {tt!r}; valid={VALID_ESCALATE_TRIGGERS}"
                )
            triggers.append(tt)

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)

    prev_mode = index.get("automation_mode", "manual")
    now = common.now_iso()

    index["automation_mode"] = args.mode

    config: dict = {
        "mode": args.mode,
        "set_at": now,
        "set_by": args.actor,
        "triggered_by": args.triggered_by or None,
    }
    if args.mode == "auto":
        config["pick_strategy"] = args.pick_strategy
        config["escalate_on"] = triggers or list(VALID_ESCALATE_TRIGGERS)
    index["automation_config"] = {k: v for k, v in config.items() if v is not None}

    common.write_project_index(args.project, index)

    common.append_generation_log(args.project, {
        "event": "set_automation_mode",
        "previous_mode": prev_mode,
        "new_mode": args.mode,
        "actor": args.actor,
        "pick_strategy": args.pick_strategy or None,
        "escalate_on": triggers or None,
        "triggered_by": args.triggered_by or None,
    })

    print(args.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
