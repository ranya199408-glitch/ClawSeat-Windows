#!/usr/bin/env python3
"""deliver_brief.py — Receiver closes a brief with the produced deliverable.

Caller: the seat that originally received the brief (writer /
builder-image / builder-av). Mirror of `dispatch_brief.py`.

Effect
------
- Validates brief exists in PROJECT_INDEX.briefs and state == "open"
- Validates --actor matches brief.target
- Validates --output-path file exists, is regular, decodes as UTF-8 text,
  is non-empty, and ≤ 5MB (text deliverable bound)
- Updates brief state=delivered + result block
  (output_path / output_size_chars / file_size / completed_at)
- Updates PROJECT_INDEX.briefs[<id>] mirror
- Appends generation_log entry (event=brief_delivered)
- Best-effort wakeup of memory's tmux pane (skip with --skip-wakeup)
- Prints brief_id to stdout

For seats that need to fail-closed a brief (e.g., model API error,
reference-learning subagent timeout), use `--fail --reason "<text>"`
instead of --output-path; sets state=failed.

Exit
----
- 0 on durable write success
- non-zero on validation / IO failure (fail-closed)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_ACTORS = ("writer", "builder-image", "builder-av")
MAX_DELIVERABLE_BYTES = 5 * 1024 * 1024  # 5MB; text deliverables only


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="deliver_brief")
    p.add_argument("--project", required=True)
    p.add_argument("--brief-id", required=True)
    p.add_argument("--actor", required=True, choices=VALID_ACTORS,
                   help="Receiver seat (must match brief.target)")
    p.add_argument("--output-path", action="append", default=[],
                   help="Path to deliverable file (relative or absolute). "
                        "Repeatable: pass once per file when the brief expected "
                        "multiple text deliverables. Order doesn't have to "
                        "match brief.deliverable_paths but coverage does — "
                        "every expected path's basename must appear in at "
                        "least one --output-path.")
    p.add_argument("--fail", action="store_true",
                   help="Mark brief failed instead of delivered "
                        "(API error / subagent timeout / etc.)")
    p.add_argument("--reason", default="",
                   help="(--fail) free-form failure reason")
    p.add_argument("--summary", default="",
                   help="Optional one-line summary of the deliverable for memory's pane")
    p.add_argument("--skip-wakeup", action="store_true")
    p.add_argument("--target-session", default="",
                   help="Explicit tmux session name to wake (overrides "
                        "brief frontmatter dispatch_session and "
                        "resolve_seat_session for memory). Resolution order: "
                        "this arg → brief.dispatch_session → "
                        "resolve_seat_session(project, 'memory').")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    common.validate_id_token(args.brief_id, kind="--brief-id")

    output_paths = [p for p in (args.output_path or []) if p.strip()]

    if args.fail and output_paths:
        common.fail_closed("--fail and --output-path are mutually exclusive")
    if not args.fail and not output_paths:
        common.fail_closed("provide either --output-path (success) or --fail (failure)")

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)
    briefs_index = index.setdefault("briefs", {})
    record = briefs_index.get(args.brief_id)
    if record is None:
        common.fail_closed(f"brief not found: {args.brief_id}")
    if record.get("state") != "open":
        common.fail_closed(
            f"brief {args.brief_id} not in 'open' state "
            f"(current state={record.get('state')!r})"
        )
    if record.get("target") != args.actor:
        common.fail_closed(
            f"actor {args.actor!r} does not match brief.target "
            f"{record.get('target')!r} for {args.brief_id}"
        )

    brief = common.load_brief(args.project, args.brief_id)
    if brief is None:
        common.fail_closed(f"brief TOML missing or malformed: briefs/{args.brief_id}.toml")

    # Audit finding #8: brief frontmatter carries the canonical project.
    # If the caller passed a different --project, fail-closed: the
    # receiver is delivering against the wrong project's index.
    fm_project = brief.get("project")
    if fm_project and fm_project != args.project:
        common.fail_closed(
            f"--project {args.project!r} disagrees with brief frontmatter "
            f"project={fm_project!r} for {args.brief_id}. "
            f"Receiver must use the brief's canonical project."
        )

    now = common.now_iso()
    outputs: list[dict[str, Any]] = []

    if output_paths:
        for raw_path in output_paths:
            output_path = Path(raw_path).expanduser()
            if not output_path.is_absolute():
                output_path = (common.project_root(args.project) / output_path).resolve()
            if not output_path.exists():
                common.fail_closed(f"deliverable file not found: {output_path}")
            if not output_path.is_file():
                common.fail_closed(f"deliverable path is not a regular file: {output_path}")
            raw = output_path.read_bytes()
            if not raw:
                common.fail_closed(f"deliverable file is empty: {output_path}")
            if len(raw) > MAX_DELIVERABLE_BYTES:
                common.fail_closed(
                    f"deliverable size {len(raw)} bytes exceeds limit "
                    f"{MAX_DELIVERABLE_BYTES} (text-only constraint): {output_path}"
                )
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                common.fail_closed(
                    f"deliverable is not valid UTF-8 text: {output_path}: {e}"
                )
            outputs.append({
                "path": str(output_path),
                "output_size_chars": len(text),
                "file_size": len(raw),
            })

        # If the brief recorded expected deliverable_paths, ensure every
        # expected basename is covered by at least one --output-path. This
        # is the protocol's coverage check: writer who is told to land
        # WORKFLOW_NOTES.md + STORY_PREMISE.md cannot quietly close with
        # only one of them.
        expected = brief.get("deliverable_paths") or []
        # Back-compat: pre-#9 briefs used singular deliverable_path string
        if not expected and brief.get("deliverable_path"):
            expected = [brief["deliverable_path"]]
        if expected:
            delivered_basenames = {Path(o["path"]).name for o in outputs}
            missing = [
                e for e in expected
                if Path(e).name and Path(e).name not in delivered_basenames
            ]
            if missing:
                common.fail_closed(
                    f"brief {args.brief_id} expects deliverables "
                    f"{expected!r} but --output-path coverage is incomplete; "
                    f"missing basenames: {missing}. "
                    f"Pass one --output-path per expected file."
                )

    # Single-output back-compat surface for tests / readers that still
    # consult record.result.output_path / .output_size_chars / .file_size.
    first_output = outputs[0] if outputs else None
    output_path_str = first_output["path"] if first_output else ""
    output_size_chars = first_output["output_size_chars"] if first_output else 0
    file_size = first_output["file_size"] if first_output else 0

    new_state = "failed" if args.fail else "delivered"
    record["state"] = new_state
    record.setdefault("result", {})
    if args.fail:
        record["result"]["failed_at"] = now
        record["result"]["failure_reason"] = args.reason
    else:
        record["result"]["delivered_at"] = now
        # Multi-output authoritative schema (always populated as a list).
        record["result"]["outputs"] = outputs
        # Single-output back-compat surface (mirrors first item) for any
        # reader still consulting the flat fields.
        record["result"]["output_path"] = output_path_str
        record["result"]["output_size_chars"] = output_size_chars
        record["result"]["file_size"] = file_size
        if args.summary:
            record["result"]["summary"] = args.summary
    common.write_project_index(args.project, index)

    # Update the brief TOML on disk to reflect new state + result.
    fm = {k: v for k, v in record.items() if k != "result"}
    fm["state"] = new_state
    body = brief.get("body", "")
    common.write_brief(args.project, args.brief_id, fm, body)
    # Append the result block separately at the tail (so the body remains
    # readable + result is parseable as TOML appended after the body
    # ends — readers should prefer PROJECT_INDEX.briefs[<id>].result).
    brief_path = common.project_root(args.project) / "briefs" / f"{args.brief_id}.toml"
    if record.get("result"):
        with brief_path.open("a", encoding="utf-8") as fh:
            fh.write("\n+++ result\n")
            fh.write(common.serialize_toml(record["result"]).rstrip("\n") + "\n")
            fh.write("+++\n")

    # Target session resolution (audit finding #9, unified in §10.6):
    #   1. explicit --target-session                  (operator override)
    #   2. brief frontmatter dispatch_session         (captured at dispatch)
    #   3. resolve_seat_session(project, "memory")    (project-bound default)
    memory_session = common.resolve_wakeup_target(args, brief=brief)
    if args.fail:
        msg = (
            f"[{args.actor}] brief_failed: {args.brief_id} "
            f"project={args.project} reason="
            f"{(args.reason or 'unspecified')[:120]}"
        )
    else:
        summary_part = f" summary={args.summary[:80]!r}" if args.summary else ""
        if len(outputs) > 1:
            paths_part = (
                f"paths=[{', '.join(o['path'] for o in outputs)}]"
            )
        else:
            paths_part = f"path={output_path_str}"
        msg = (
            f"[{args.actor}] brief_delivered: {args.brief_id} "
            f"project={args.project} {paths_part}{summary_part}; "
            f"read ~/.cartooner/projects/{args.project}/briefs/{args.brief_id}.toml"
        )
    wakeup = common.send_wakeup(
        args.project,
        memory_session,
        msg,
        skip=args.skip_wakeup,
    )

    common.append_generation_log(args.project, {
        "event": "brief_delivered" if not args.fail else "brief_failed",
        "brief_id": args.brief_id,
        "actor": args.actor,
        "target": args.actor,           # same; receiver-as-actor for audit
        "output_path": output_path_str or None,
        "output_size_chars": output_size_chars or None,
        "file_size": file_size or None,
        "outputs": outputs or None,
        "summary": args.summary or None,
        "failure_reason": args.reason if args.fail else None,
        "wakeup_ok": wakeup["ok"],
        "wakeup_reason": wakeup["reason"],
    })

    if not wakeup["ok"] and not args.skip_wakeup:
        sys.stderr.write(
            f"[deliver_brief] WARN wakeup failed: {wakeup['reason']}\n"
        )

    print(args.brief_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
