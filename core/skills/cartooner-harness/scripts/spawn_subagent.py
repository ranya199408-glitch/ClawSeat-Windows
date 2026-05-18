#!/usr/bin/env python3
"""spawn_subagent.py — Allocate / complete / fail a subagent invocation.

Caller: `builder-image` or `builder-av` ONLY (writer / memory / patrol
cannot spawn subagents — they have no use case for vision-isolated
analysis under no-image-policy).

This is the v2 hardening of the subagent contract documented in
`references/subagent-protocol.md`. It replaces the looser
`report_to_memory.py --event subagent_started` path with strict id
allocation + report-file validation. The two paths coexist for backward
compat, but new code should use this script.

Three actions
-------------
spawn
  Allocates subagent_id (sa-rc-<hex> or sa-ref-<hex>), writes the
  state record to subagents/<id>.toml, registers in
  PROJECT_INDEX.subagents[<id>], appends `subagent_spawned` to log,
  prints subagent_id.

complete
  Validates the report file exists, is a regular file, decodes as UTF-8
  text, and is non-empty (≤ 1MB). Updates state=completed, records
  output_size_chars + report_path, appends `subagent_completed` event,
  prints subagent_id.

fail
  Marks state=failed with --reason, appends `subagent_failed` event.

The protocol-level no-image-policy boundary is enforced by:

1. Caller must be builder-image / builder-av (text-only seats forbidden)
2. Report file must decode as text (binary fails closed)
3. Report file must be ≤ 1MB (large reports are suspicious; raw image
   bytes embedded as base64 would blow this limit)

Exit
----
- 0 on success
- non-zero on validation failure (fail-closed)
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_ACTIONS = ("spawn", "complete", "fail")
VALID_CALLERS = ("builder-image", "builder-av")
VALID_TYPES = ("root_cause", "reference_learning")
VALID_STATES = ("spawned", "completed", "failed")

MAX_REPORT_BYTES = 1_048_576   # 1 MB; reports with embedded image bytes blow this


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="spawn_subagent")
    p.add_argument("--project", required=True)
    p.add_argument("--action", required=True, choices=VALID_ACTIONS)

    # spawn-only
    p.add_argument("--seat", default="", choices=("",) + VALID_CALLERS,
                   help="(spawn) Calling seat (builder-image | builder-av)")
    p.add_argument("--subagent-type", default="", choices=("",) + VALID_TYPES,
                   help="(spawn) root_cause | reference_learning")
    p.add_argument("--inputs", default="{}",
                   help="(spawn) JSON inputs (candidate_ids, user_feedback, "
                        "reference_url, focus, etc.)")
    p.add_argument("--parent-round", default="",
                   help="(spawn root_cause) tournament round_id this analysis ties to")
    p.add_argument("--parent-shot", default="",
                   help="(spawn) shot_id this subagent informs")

    # complete-only
    p.add_argument("--subagent-id", default="",
                   help="(complete | fail) subagent id returned by spawn")
    p.add_argument("--report-path", default="",
                   help="(complete) Path to the subagent's text report under "
                        "references_learned/")

    # fail-only
    p.add_argument("--reason", default="",
                   help="(fail) Free-form failure reason")

    # spawn-only concurrency cap (audit finding #12)
    p.add_argument("--max-concurrent", type=int, default=4,
                   help="(spawn) Maximum number of subagents this caller may "
                        "have in 'spawned' (not yet completed/failed) state at "
                        "once. Fails closed if exceeded. Audit finding #12 "
                        "(2026-05-11): Gemini's function-calling API rejects "
                        "follow-on turns when prior parallel tool calls have "
                        "unmatched response parts — builder-av (Gemini-backed) "
                        "should pass --max-concurrent 1 to spawn subagents "
                        "strictly sequentially. Codex / Claude callers can "
                        "leave the default of 4.")

    return p.parse_args(argv)


def make_subagent_id(subagent_type: str) -> str:
    prefix = "sa-rc" if subagent_type == "root_cause" else "sa-ref"
    return f"{prefix}-{secrets.token_hex(4)}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.action == "spawn":
        return _spawn(args)
    if args.action == "complete":
        return _complete(args)
    if args.action == "fail":
        return _fail(args)
    common.fail_closed(f"unknown --action: {args.action}")  # pragma: no cover
    return 1  # pragma: no cover


def _spawn(args: argparse.Namespace) -> int:
    if not args.seat:
        common.fail_closed("--action spawn requires --seat")
    if not args.subagent_type:
        common.fail_closed("--action spawn requires --subagent-type")

    try:
        inputs = json.loads(args.inputs)
    except json.JSONDecodeError as e:
        common.fail_closed(f"invalid --inputs JSON: {e}")
    if not isinstance(inputs, dict):
        common.fail_closed("--inputs must be a JSON object")

    # type-specific input validation
    if args.subagent_type == "root_cause":
        if not inputs.get("candidate_ids"):
            common.fail_closed(
                "root_cause subagent requires inputs.candidate_ids "
                "(list of asset ids to analyze)"
            )
        if not inputs.get("user_feedback"):
            common.fail_closed(
                "root_cause subagent requires inputs.user_feedback "
                "(prevents self-eval; must be triggered by user input)"
            )
    if args.subagent_type == "reference_learning":
        if not inputs.get("reference_url"):
            common.fail_closed(
                "reference_learning subagent requires inputs.reference_url"
            )

    common.ensure_project_skeleton(args.project)

    if args.max_concurrent < 1:
        common.fail_closed(
            f"--max-concurrent must be >= 1, got {args.max_concurrent}"
        )

    # Audit finding #12: enforce per-caller concurrency cap before any
    # state mutation. Counts only "spawned" (in-flight) subagents from
    # the same caller — completed / failed don't count.
    index_pre = common.load_project_index(args.project)
    in_flight = [
        sa for sa in (index_pre.get("subagents") or {}).values()
        if sa.get("state") == "spawned" and sa.get("caller") == args.seat
    ]
    if len(in_flight) >= args.max_concurrent:
        in_flight_ids = sorted(sa.get("id", "<no-id>") for sa in in_flight)
        common.fail_closed(
            f"--max-concurrent={args.max_concurrent} exceeded: caller "
            f"{args.seat!r} already has {len(in_flight)} spawned "
            f"subagents in flight ({in_flight_ids}). Complete or fail "
            f"them first (spawn_subagent.py --action complete/fail). "
            f"Lower --max-concurrent if you want strict serialization."
        )

    if args.parent_round:
        index_check = common.load_project_index(args.project)
        if args.parent_round not in index_check.get("tournaments", {}):
            common.fail_closed(
                f"--parent-round not in PROJECT_INDEX.tournaments: {args.parent_round}"
            )

    subagent_id = make_subagent_id(args.subagent_type)
    now = common.now_iso()

    # ensure subagents/ directory exists
    subagents_dir = common.project_root(args.project) / "subagents"
    subagents_dir.mkdir(parents=True, exist_ok=True)

    record: dict = {
        "id": subagent_id,
        "type": args.subagent_type,
        "caller": args.seat,
        "state": "spawned",
        "spawned_at": now,
        "parent_round": args.parent_round,
        "parent_shot": args.parent_shot,
        "inputs": inputs,
    }

    sa_path = subagents_dir / f"{subagent_id}.toml"
    sa_path.write_text(common.serialize_toml(record), encoding="utf-8")

    def _add_subagent(index):
        index.setdefault("subagents", {})[subagent_id] = {
            "id": subagent_id,
            "type": args.subagent_type,
            "caller": args.seat,
            "state": "spawned",
            "spawned_at": now,
            "parent_round": args.parent_round or None,
            "parent_shot": args.parent_shot or None,
        }
        return index
    common.update_project_index(args.project, _add_subagent)

    common.append_generation_log(args.project, {
        "event": "subagent_spawned",
        "subagent_id": subagent_id,
        "subagent_type": args.subagent_type,
        "actor": args.seat,
        "caller": args.seat,
        "parent_round": args.parent_round or None,
        "parent_shot": args.parent_shot or None,
        "inputs": inputs,
    })

    print(subagent_id)
    return 0


def _complete(args: argparse.Namespace) -> int:
    if not args.subagent_id:
        common.fail_closed("--action complete requires --subagent-id")
    common.validate_id_token(args.subagent_id, kind="--subagent-id")
    if not args.report_path:
        common.fail_closed("--action complete requires --report-path")

    report_path = Path(args.report_path).expanduser()
    if not report_path.exists():
        common.fail_closed(f"report file not found: {report_path}")
    if not report_path.is_file():
        common.fail_closed(f"report path is not a regular file: {report_path}")

    raw = report_path.read_bytes()
    if not raw:
        common.fail_closed(f"report file is empty: {report_path}")
    if len(raw) > MAX_REPORT_BYTES:
        common.fail_closed(
            f"report file size {len(raw)} bytes exceeds limit {MAX_REPORT_BYTES} "
            f"(reports must be text-only; binary content suggests no-image-policy violation)"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        common.fail_closed(
            f"report file is not valid UTF-8 text: {e} "
            f"(no-image-policy: subagent reports must be text-only)"
        )

    output_size_chars = len(text)
    file_size = len(raw)

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)
    sa_index = index.setdefault("subagents", {}).get(args.subagent_id)
    if sa_index is None:
        common.fail_closed(f"subagent not found: {args.subagent_id}")
    if sa_index.get("state") != "spawned":
        common.fail_closed(
            f"subagent {args.subagent_id} is not in spawned state "
            f"(current state={sa_index.get('state')!r})"
        )

    now = common.now_iso()
    sa_index["state"] = "completed"
    sa_index["completed_at"] = now
    sa_index["report_path"] = str(report_path)
    sa_index["output_size_chars"] = output_size_chars
    common.write_project_index(args.project, index)

    sa_file_path = common.project_root(args.project) / "subagents" / f"{args.subagent_id}.toml"
    if sa_file_path.exists():
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[no-redef]
        with sa_file_path.open("rb") as fh:
            existing = tomllib.load(fh)
        existing["state"] = "completed"
        existing.setdefault("result", {})
        existing["result"]["report_path"] = str(report_path)
        existing["result"]["output_size_chars"] = output_size_chars
        existing["result"]["file_size"] = file_size
        existing["result"]["completed_at"] = now
        sa_file_path.write_text(common.serialize_toml(existing), encoding="utf-8")

    common.append_generation_log(args.project, {
        "event": "subagent_completed",
        "subagent_id": args.subagent_id,
        "actor": sa_index.get("caller"),
        "caller": sa_index.get("caller"),
        "subagent_type": sa_index.get("type"),
        "report_path": str(report_path),
        "output_size_chars": output_size_chars,
        "file_size": file_size,
    })

    print(args.subagent_id)
    return 0


def _fail(args: argparse.Namespace) -> int:
    if not args.subagent_id:
        common.fail_closed("--action fail requires --subagent-id")
    common.validate_id_token(args.subagent_id, kind="--subagent-id")

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)
    sa_index = index.setdefault("subagents", {}).get(args.subagent_id)
    if sa_index is None:
        common.fail_closed(f"subagent not found: {args.subagent_id}")
    if sa_index.get("state") != "spawned":
        common.fail_closed(
            f"subagent {args.subagent_id} is not in spawned state "
            f"(current state={sa_index.get('state')!r})"
        )

    now = common.now_iso()
    sa_index["state"] = "failed"
    sa_index["failed_at"] = now
    sa_index["failure_reason"] = args.reason
    common.write_project_index(args.project, index)

    sa_file_path = common.project_root(args.project) / "subagents" / f"{args.subagent_id}.toml"
    if sa_file_path.exists():
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[no-redef]
        with sa_file_path.open("rb") as fh:
            existing = tomllib.load(fh)
        existing["state"] = "failed"
        existing.setdefault("result", {})
        existing["result"]["failed_at"] = now
        existing["result"]["failure_reason"] = args.reason
        sa_file_path.write_text(common.serialize_toml(existing), encoding="utf-8")

    common.append_generation_log(args.project, {
        "event": "subagent_failed",
        "subagent_id": args.subagent_id,
        "actor": sa_index.get("caller"),
        "caller": sa_index.get("caller"),
        "subagent_type": sa_index.get("type"),
        "reason": args.reason,
    })

    print(args.subagent_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
