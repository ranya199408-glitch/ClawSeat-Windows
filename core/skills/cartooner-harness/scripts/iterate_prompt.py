#!/usr/bin/env python3
"""iterate_prompt.py — Record a user-feedback iteration request.

Backend-only iteration ledger. Records WHO gave WHAT feedback about
WHICH parent (lane / shot / project) at WHICH layer. The caller (memory)
is responsible for the actual dispatch action that follows.

Layer semantics
---------------
- L1: brief / vision_spec / style_bible level — caller opens conversation
  with user to revise high-level intent
- L2: narrative_outline.md / shot_list.toml level — caller dispatches
  writer (narrative) or builder-av (shot_list)
- L3: model-prompt level — caller re-spawns the target lane with
  builder-* adjusting prompt based on feedback

Caller flow (memory)
--------------------
1. memory receives feedback (from user_direct, pick_winner reject_all, etc.)
2. memory classifies the feedback layer (L1 / L2 / L3) using its own LLM
   reasoning — typically by reading the feedback text
3. memory subprocess.run(iterate_prompt.py --layer LX --feedback "<text>" ...)
4. memory takes the dispatch action implied by --layer:
   - L1 → use AskUserQuestion to confirm brief/style_bible revision
   - L2 → dispatch writer or builder-av to revise text artifact
   - L3 → spawn_lane with adjusted prompt

Effect
------
- Writes iterations/<iter-id>.toml
- Records iteration in PROJECT_INDEX.iterations
- Appends generation_log (event=iterate_prompt)
- Prints iter_id to stdout

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

VALID_LAYERS = ("L1", "L2", "L3")
VALID_ACTORS = ("user", "memory_acting_director")
VALID_TRIGGERS = (
    "",
    "user_direct",
    "pick_winner_reject_all",
    "tournament_failed",
    "auto_iterate",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="iterate_prompt")
    p.add_argument("--project", required=True)
    p.add_argument("--layer", required=True, choices=VALID_LAYERS,
                   help="Caller's classification of which layer needs adjustment")
    p.add_argument("--feedback", required=True,
                   help="User feedback text (free-form; non-empty)")
    p.add_argument("--parent-lane", default="",
                   help="(L3) Lane id this iteration targets")
    p.add_argument("--parent-shot", default="",
                   help="(L2 / L3) Shot id this iteration relates to (cross-modal join)")
    p.add_argument("--target", default="",
                   help="What artifact is being iterated: lane / shot_list / "
                        "narrative_outline / brief / style_bible / character_dna")
    p.add_argument("--actor", default="user", choices=VALID_ACTORS)
    p.add_argument("--triggered-by-event", default="", choices=VALID_TRIGGERS,
                   help="Upstream event that produced this feedback")
    return p.parse_args(argv)


def make_iter_id(layer: str) -> str:
    return f"iter-{layer.lower()}-{secrets.token_hex(4)}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.feedback.strip():
        common.fail_closed("--feedback must be non-empty")

    if args.layer == "L3" and not args.parent_lane:
        common.fail_closed("--layer L3 requires --parent-lane")

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)

    if args.parent_lane:
        common.validate_id_token(args.parent_lane, kind="--parent-lane")
        if args.parent_lane not in index.get("lanes", {}):
            common.fail_closed(
                f"--parent-lane not in PROJECT_INDEX.lanes: {args.parent_lane}"
            )

    iter_id = make_iter_id(args.layer)
    now = common.now_iso()

    record: dict = {
        "id": iter_id,
        "layer": args.layer,
        "feedback": args.feedback,
        "parent_lane": args.parent_lane,
        "parent_shot": args.parent_shot,
        "target": args.target,
        "actor": args.actor,
        "triggered_by_event": args.triggered_by_event,
        "created_at": now,
        "status": "open",
    }

    iter_dir = common.project_root(args.project) / "iterations"
    iter_dir.mkdir(parents=True, exist_ok=True)
    iter_path = iter_dir / f"{iter_id}.toml"
    iter_path.write_text(common.serialize_toml(record), encoding="utf-8")

    index.setdefault("iterations", {})[iter_id] = record
    common.write_project_index(args.project, index)

    common.append_generation_log(args.project, {
        "event": "iterate_prompt",
        "iter_id": iter_id,
        "layer": args.layer,
        "feedback": args.feedback,
        "parent_lane": args.parent_lane or None,
        "parent_shot": args.parent_shot or None,
        "target": args.target or None,
        "actor": args.actor,
        "triggered_by_event": args.triggered_by_event or None,
    })

    print(iter_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
