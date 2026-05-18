#!/usr/bin/env python3
"""dispatch_brief.py — Dispatch a single-deliverable handoff to a seat.

Caller: `memory` (default) — or any seat self-dispatching after a
user-direct request has been reported (Producer-centric override).

The brief is the single-deliverable counterpart to a tournament `lane`:
when memory wants ONE artifact (revised shot_list / narrative_outline /
character_dna / reference_learning report), it writes a brief and wakes
the target seat. The receiver reads the brief, executes, and closes via
`deliver_brief.py`.

See `references/communication-protocol.md` §2.2 for the full contract.

Effect
------
- Generates a unique brief_id (brief-<short-hash>)
- Writes briefs/<id>.toml with `+++` frontmatter + markdown body
- Updates PROJECT_INDEX.briefs[<id>]
- Appends generation_log entry (event=brief_dispatched)
- Best-effort wakeup of target seat's tmux pane via send-and-verify.sh
  (skip with --skip-wakeup; tests do this since no live tmux exists)
- Prints brief_id to stdout

Exit
----
- 0 on durable write success (wakeup failures are warnings, not blockers)
- non-zero on validation / IO failure (fail-closed)
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_TARGETS = ("writer", "builder-image", "builder-av")
VALID_INTENTS = (
    "narrative",
    "lyric",
    "copy",
    "shot_list_revision",
    "reference_learning",
    "dna",
    "other",
)
VALID_TRIGGERS = (
    "memory_dispatch",
    "user_direct",
    "iterate_prompt",
    "auto_iterate",
)
VALID_ACTORS = ("memory", "writer", "builder-image", "builder-av")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="dispatch_brief")
    p.add_argument("--project", required=True)
    p.add_argument("--target", required=True, choices=VALID_TARGETS,
                   help="Receiver seat (writer / builder-image / builder-av)")
    p.add_argument("--intent", required=True, choices=VALID_INTENTS)
    p.add_argument("--body", default="",
                   help="Markdown body text (read --body-file instead for long content)")
    p.add_argument("--body-file", default="",
                   help="Path to a markdown file used as brief body "
                        "(takes precedence over --body)")
    p.add_argument("--deliverable-path", action="append", default=[],
                   help="Relative path under project root where receiver should "
                        "land the deliverable (e.g. narrative_outline.md). "
                        "Repeatable: pass once per file when the brief expects "
                        "multiple text deliverables (e.g. WORKFLOW_NOTES.md + "
                        "STORY_PREMISE.md). Stored as deliverable_paths list "
                        "in the brief frontmatter.")
    p.add_argument("--parent-lane", default="")
    p.add_argument("--parent-shot", default="")
    p.add_argument("--triggered-by", default="memory_dispatch", choices=VALID_TRIGGERS)
    p.add_argument("--actor", default="memory", choices=VALID_ACTORS,
                   help="Caller seat id (default memory; for user-direct self-dispatch "
                        "set this to the seat itself)")
    p.add_argument("--skip-wakeup", action="store_true",
                   help="Skip tmux wakeup (tests / dry runs)")
    p.add_argument("--target-session", default="",
                   help="Explicit tmux session name to wake (overrides "
                        "resolve_seat_session). Use when target seat's tmux "
                        "is bound to a different project than --project.")
    p.add_argument("--dispatch-session", default="",
                   help="Tmux session name of the dispatching seat (memory). "
                       "Captured in brief frontmatter so deliver_brief can wake "
                       "back the actual dispatcher session even when it's "
                       "bound to a different project than --project. Defaults "
                       "to the current tmux session (auto-detected via "
                       "$TMUX + `tmux display-message`); pass explicitly when "
                       "calling from outside tmux or when auto-detection picks "
                       "the wrong window.")
    return p.parse_args(argv)


def make_brief_id() -> str:
    return f"brief-{secrets.token_hex(4)}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    body = args.body or ""
    if args.body_file:
        body_path = Path(args.body_file).expanduser()
        if not body_path.exists() or not body_path.is_file():
            common.fail_closed(f"--body-file not found: {body_path}")
        body = body_path.read_text(encoding="utf-8")
    if not body.strip():
        common.fail_closed("brief body must be non-empty (use --body or --body-file)")

    if args.actor != "memory" and args.triggered_by != "user_direct":
        common.fail_closed(
            f"non-memory actor {args.actor!r} may dispatch only with "
            f"--triggered-by user_direct (Producer-centric override). "
            f"Got --triggered-by {args.triggered_by!r}."
        )
    if args.triggered_by == "user_direct" and args.actor not in ("writer", "builder-image", "builder-av"):
        common.fail_closed(
            f"--triggered-by user_direct requires --actor to be the seat that "
            f"received the user direct (writer / builder-image / builder-av); got {args.actor!r}"
        )
    # Hub-and-spoke (communication-protocol.md §7): non-memory dispatchers
    # may only self-dispatch (target == actor). Lateral dispatch
    # (writer → builder-av etc.) is forbidden — it must round-trip through
    # memory so the project's single source of truth stays informed.
    if args.actor != "memory" and args.target != args.actor:
        common.fail_closed(
            f"hub-and-spoke violation: non-memory actor {args.actor!r} may "
            f"only self-dispatch (target must equal actor); got "
            f"target={args.target!r}. Lateral seat-to-seat dispatch is "
            f"forbidden — route through memory instead."
        )

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)

    if args.parent_lane:
        common.validate_id_token(args.parent_lane, kind="--parent-lane")
        if args.parent_lane not in index.get("lanes", {}):
            common.fail_closed(
                f"--parent-lane not in PROJECT_INDEX.lanes: {args.parent_lane}"
            )

    brief_id = make_brief_id()
    now = common.now_iso()

    # Normalize --deliverable-path (now action="append"). Strip empties so
    # callers passing `--deliverable-path ""` don't poison the list.
    deliverable_paths = [p for p in (args.deliverable_path or []) if p.strip()]

    # Audit finding #9: capture dispatcher's tmux session in frontmatter so
    # the receiver's deliver_brief can wake memory back even when memory's
    # tmux is bound to a different project than the brief's --project.
    # Auto-detect from $TMUX when --dispatch-session not given.
    dispatch_session = args.dispatch_session.strip() or (
        common.detect_tmux_session() or ""
    )

    frontmatter: dict = {
        "id": brief_id,
        # project is canonical here — the receiver MUST use this exact
        # project_id when calling deposit_asset / deliver_brief / etc.
        # Prevents project context drift (audit finding #8): without an
        # explicit anchor the receiver's LLM falls back to its own
        # session-bound default project.
        "project": args.project,
        "created_at": now,
        "source": "memory" if args.triggered_by != "user_direct" else f"user_direct:{args.actor}",
        "target": args.target,
        "intent": args.intent,
        "parent_lane": args.parent_lane,
        "parent_shot": args.parent_shot,
        "deliverable_paths": deliverable_paths,
        "dispatch_session": dispatch_session,
        "triggered_by": args.triggered_by,
        "actor": args.actor,
        "state": "open",
    }

    common.write_brief(args.project, brief_id, frontmatter, body)

    index_record = dict(frontmatter)
    index_record.pop("body", None)
    index.setdefault("briefs", {})[brief_id] = index_record
    common.write_project_index(args.project, index)

    # Unified 3-layer resolution (audit §10.6): explicit > brief.dispatch_session
    # > resolve_seat_session(project, target). No brief dict at dispatch time,
    # so only layers 1 and 3 apply here; fallback_seat=args.target is correct.
    target_session = common.resolve_wakeup_target(args, fallback_seat=args.target)
    # Wakeup message MUST name the project explicitly (audit finding #8).
    # Without --project in the wakeup, the receiver's LLM tends to fall
    # back to its own session-bound default project and deposit assets
    # in the wrong PROJECT_INDEX. Also surfaces deliverable_paths so the
    # receiver doesn't have to grep the body for file names.
    paths_hint = (
        f" deliverables=[{', '.join(deliverable_paths)}]"
        if deliverable_paths else ""
    )
    wakeup_message = (
        f"[memory] brief_dispatched: {brief_id} project={args.project} "
        f"intent={args.intent} target={args.target}{paths_hint}; "
        f"read ~/.cartooner/projects/{args.project}/briefs/{brief_id}.toml. "
        f"All downstream protocol calls MUST pass --project {args.project}."
    )
    wakeup = common.send_wakeup(
        args.project,
        target_session,
        wakeup_message,
        skip=args.skip_wakeup,
    )

    common.append_generation_log(args.project, {
        "event": "brief_dispatched",
        "brief_id": brief_id,
        "target": args.target,
        "intent": args.intent,
        "actor": args.actor,
        "triggered_by": args.triggered_by,
        "parent_lane": args.parent_lane or None,
        "parent_shot": args.parent_shot or None,
        "deliverable_paths": deliverable_paths or None,
        "dispatch_session": dispatch_session or None,
        "wakeup_ok": wakeup["ok"],
        "wakeup_reason": wakeup["reason"],
    })

    if not wakeup["ok"] and not args.skip_wakeup:
        sys.stderr.write(
            f"[dispatch_brief] WARN wakeup failed: {wakeup['reason']} "
            f"(brief is durable; receiver can pull via render_asset_tree)\n"
        )

    print(brief_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
