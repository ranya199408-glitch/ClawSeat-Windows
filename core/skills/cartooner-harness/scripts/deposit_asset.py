#!/usr/bin/env python3
"""deposit_asset.py — Persist a generated asset with metadata only.

Caller: `builder-image` or `builder-av` after API generation completes.

no-image-policy
---------------
This script NEVER reads asset content. It only:
- stat()s the asset file for size + existence
- captures model-provided metadata (passed as --model-metadata JSON)
- captures generation params (prompt_l3, seed, model)

If you find yourself wanting to load image bytes here, you are violating
the protocol. See `references/no-image-policy.md`.

Effect
------
- Validates the lane exists and the actor matches the lane's seat
- Validates asset_type matches the actor (image -> builder-image only;
  video / audio -> builder-av only)
- Records asset metadata in PROJECT_INDEX.assets[<asset_id>]
- Appends asset_id to lane.result.candidates
- Transitions lane state to "generating" or, with --all-candidates-deposited,
  to "deposited"
- Appends generation_log entry (event=asset_deposited)

Exit
----
- 0 on success
- non-zero on validation / IO failure (fail-closed)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_DEPOSIT_ACTORS = ("builder-image", "builder-av", "writer")
VALID_TYPES_PER_ACTOR = {
    "builder-image": ("image",),
    "builder-av": ("video", "audio"),
    "writer": ("text",),
}
MAX_TEXT_ASSET_BYTES = 5 * 1024 * 1024  # 5MB; mirrors deliver_brief constraint


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="deposit_asset")
    p.add_argument("--project", required=True)
    p.add_argument("--lane-id", required=True)
    p.add_argument("--asset-id", default="",
                   help="Unique asset id (e.g. img-042-a). Required for "
                        "deposit; ignored for --fail-lane.")
    p.add_argument("--asset-path", default="",
                   help="Path to deposited asset file (must exist + size > 0). "
                        "Required for deposit; ignored for --fail-lane.")
    p.add_argument("--actor", required=True, choices=VALID_DEPOSIT_ACTORS,
                   help="Depositing seat (must match lane.seat)")
    p.add_argument("--asset-type", default="", choices=("",) + common.VALID_ASSET_TYPES,
                   help="Asset type. Required for deposit; ignored for --fail-lane.")
    p.add_argument("--prompt-l3", default="", help="Model-specific prompt used")
    p.add_argument("--model", default="",
                   help="e.g. nano-banana, gpt-image-2, seedance-2.0-i2v")
    p.add_argument("--seed", type=int, default=None,
                   help="Generation seed if known")
    p.add_argument("--api-status", default="200",
                   help="API response status (default 200)")
    p.add_argument("--model-metadata", default="{}",
                   help="JSON-encoded model-provided metadata "
                        "(aesthetic_score / safety / etc)")
    p.add_argument("--all-candidates-deposited", action="store_true",
                   help="Set lane state=deposited (final candidate landed)")
    p.add_argument("--skip-wakeup", action="store_true",
                   help="Skip tmux wakeup of memory pane on final deposit")
    p.add_argument("--target-session", default="",
                   help="Explicit memory tmux session name (overrides "
                        "resolve_seat_session). Use when memory's tmux is "
                        "bound to a different project than --project.")
    p.add_argument("--model-fallback-reason", default="",
                   help="Required when --model differs from lane.model "
                        "(audit finding #10). Forces silent provider "
                        "fallback to be an explicit, audited signal: e.g. "
                        "'OpenAI route 401', 'Imagen API quota exceeded'. "
                        "If lane has no model intent, this arg is ignored. "
                        "If --model matches lane.model, this arg is ignored.")
    p.add_argument("--fail-lane", action="store_true",
                   help="Audit finding #14 (2026-05-11): mark the lane as "
                        "failed without depositing any asset. Use when the "
                        "requested model.intent route is genuinely "
                        "unreachable (e.g., codex-image-builtin with no "
                        "chatgpt access). Requires --reason. Mutually "
                        "exclusive with the deposit args (--asset-id / "
                        "--asset-path / --asset-type / --model). Memory "
                        "may then re-spawn with a different model + "
                        "parent-lane=<this>.")
    p.add_argument("--reason", default="",
                   help="(--fail-lane) free-form reason the lane could not "
                        "produce an asset (e.g., 'codex-image-builtin route "
                        "unavailable in this codex auth tier').")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    common.validate_id_token(args.lane_id, kind="--lane-id")

    # Audit finding #14: --fail-lane is the no-deposit path. Branch
    # before any asset validation so deposit-required args are skipped.
    if args.fail_lane:
        return _fail_lane(args)

    if not args.asset_id:
        common.fail_closed("deposit requires --asset-id (or use --fail-lane)")
    if not args.asset_path:
        common.fail_closed("deposit requires --asset-path (or use --fail-lane)")
    if not args.asset_type:
        common.fail_closed("deposit requires --asset-type (or use --fail-lane)")

    common.validate_id_token(args.asset_id, kind="--asset-id")

    asset_path = Path(args.asset_path).expanduser()
    if not asset_path.exists():
        common.fail_closed(f"asset file not found: {asset_path}")
    if not asset_path.is_file():
        common.fail_closed(f"asset path is not a file: {asset_path}")

    file_size = asset_path.stat().st_size
    if file_size <= 0:
        common.fail_closed(f"asset file is empty: {asset_path}")

    try:
        model_metadata = json.loads(args.model_metadata)
    except json.JSONDecodeError as e:
        common.fail_closed(f"invalid --model-metadata JSON: {e}")

    if args.asset_type not in VALID_TYPES_PER_ACTOR[args.actor]:
        common.fail_closed(
            f"actor {args.actor!r} cannot deposit asset_type={args.asset_type!r}"
        )

    # Text-asset constraints (writer's lane outputs):
    # - must be UTF-8 (no binary contamination)
    # - must be ≤ 5MB (mirrors deliver_brief; binary suggests boundary violation)
    if args.asset_type == "text":
        if file_size > MAX_TEXT_ASSET_BYTES:
            common.fail_closed(
                f"text asset {file_size} bytes exceeds {MAX_TEXT_ASSET_BYTES} "
                f"(text-only constraint)"
            )
        try:
            asset_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            common.fail_closed(
                f"text asset is not valid UTF-8: {e} "
                f"(no-image-policy: writer outputs are text-only)"
            )

    lane = common.load_lane(args.project, args.lane_id)
    if lane is None:
        common.fail_closed(f"lane not found: {args.lane_id}")

    if lane.get("seat") != args.actor:
        common.fail_closed(
            f"actor mismatch: lane.seat={lane.get('seat')!r} actor={args.actor!r}"
        )

    if lane.get("state") in ("superseded", "failed"):
        common.fail_closed(
            f"cannot deposit into lane {args.lane_id} (state={lane.get('state')})"
        )

    # Audit finding #10 (2026-05-11): silent provider fallback breaks
    # cross-model comparison tests. If memory anchored a model intent on
    # the lane and the deposit's --model disagrees, the depositor MUST
    # justify the fallback via --model-fallback-reason. The asset record
    # then carries both `model_asked` (lane intent) and `model` (actual)
    # so downstream readers can audit the divergence.
    lane_model = (lane.get("model") or "").strip()
    actual_model = (args.model or "").strip()
    fallback_reason = args.model_fallback_reason.strip()
    model_diverged = bool(lane_model) and bool(actual_model) and lane_model != actual_model
    if model_diverged and not fallback_reason:
        common.fail_closed(
            f"deposit_asset --model={actual_model!r} disagrees with "
            f"lane.model={lane_model!r}. Pass --model-fallback-reason "
            f"\"<why>\" to record the divergence as an audit signal "
            f"(silent provider fallback is forbidden by audit finding #10)."
        )

    now = common.now_iso()
    final = bool(args.all_candidates_deposited)
    new_state = "deposited" if final else "generating"

    asset_record = {
        "asset_id": args.asset_id,
        "path": str(asset_path),
        "type": args.asset_type,
        "lane": args.lane_id,
        "model": args.model,
        # Audit finding #10: capture lane's requested model so downstream
        # readers see (asked, actual) pair and can detect silent fallback.
        "model_asked": lane_model or None,
        "model_fallback_reason": fallback_reason or None,
        "seed": args.seed,
        "api_status": args.api_status,
        "file_size": file_size,
        "model_metadata": model_metadata,
        "deposited_at": now,
        "triggered_by": lane.get("triggered_by", "memory_spawn"),
    }

    index = common.load_project_index(args.project)
    index.setdefault("assets", {})[args.asset_id] = asset_record
    lane_idx = index.setdefault("lanes", {}).setdefault(args.lane_id, {})
    lane_idx["state"] = new_state
    if final:
        lane_idx["deposited_at"] = now
    common.write_project_index(args.project, index)

    lane.setdefault("result", {}).setdefault("candidates", [])
    if args.asset_id not in lane["result"]["candidates"]:
        lane["result"]["candidates"].append(args.asset_id)
    lane["state"] = new_state
    if final:
        lane["result"]["deposited_at"] = now
    common.write_lane(args.project, args.lane_id, lane)

    # Wake memory ONLY on the lane-final deposit (state flipped to
    # "deposited"). Individual non-final deposits accumulate silently —
    # no need to spam memory's pane between candidates.
    wakeup_ok = None
    wakeup_reason = None
    if final:
        memory_session = common.resolve_wakeup_target(args)
        wakeup_message = (
            f"[{args.actor}] lane_completed: {args.lane_id} "
            f"project={args.project} "
            f"({len(lane['result']['candidates'])} {args.asset_type} candidates ready); "
            f"run pick_winner.py --project {args.project} --round-id <id> "
            f"--candidates <comma-list>"
        )
        wakeup = common.send_wakeup(
            args.project,
            memory_session,
            wakeup_message,
            skip=args.skip_wakeup,
        )
        wakeup_ok = wakeup["ok"]
        wakeup_reason = wakeup["reason"]
        if not wakeup_ok and not args.skip_wakeup:
            sys.stderr.write(
                f"[deposit_asset] WARN wakeup failed: {wakeup_reason} "
                f"(lane is durable; memory can pull via render_asset_tree)\n"
            )

    common.append_generation_log(args.project, {
        "event": "asset_deposited",
        "lane_id": args.lane_id,
        "asset_id": args.asset_id,
        "asset_type": args.asset_type,
        "actor": args.actor,
        "model": args.model,
        "model_asked": lane_model or None,
        "model_fallback_reason": fallback_reason or None,
        "seed": args.seed,
        "prompt_l3": args.prompt_l3,
        "api_status": args.api_status,
        "file_size": file_size,
        "model_metadata": model_metadata,
        "lane_final": final,
        "wakeup_ok": wakeup_ok,
        "wakeup_reason": wakeup_reason,
    })

    print(args.asset_id)
    return 0


def _fail_lane(args: argparse.Namespace) -> int:
    """Audit finding #14: transition lane to state=failed without depositing.

    Used when the lane's requested model intent is unreachable in this
    seat's runtime (e.g., codex-image-builtin with no chatgpt access) and
    the right action is to escalate to memory rather than silent fallback.
    Memory may then re-spawn with a different model + parent_lane=<this>.
    """
    if not args.reason.strip():
        common.fail_closed("--fail-lane requires --reason")
    if args.asset_id or args.asset_path or args.asset_type:
        common.fail_closed(
            "--fail-lane is mutually exclusive with --asset-id / "
            "--asset-path / --asset-type (no asset is being deposited)"
        )

    lane = common.load_lane(args.project, args.lane_id)
    if lane is None:
        common.fail_closed(f"lane not found: {args.lane_id}")
    if lane.get("seat") != args.actor:
        common.fail_closed(
            f"actor mismatch: lane.seat={lane.get('seat')!r} "
            f"actor={args.actor!r}"
        )
    if lane.get("state") in ("deposited", "picked", "superseded", "failed"):
        common.fail_closed(
            f"cannot fail-lane {args.lane_id} (state={lane.get('state')}); "
            f"--fail-lane is only valid for spawned/generating lanes"
        )

    now = common.now_iso()
    lane["state"] = "failed"
    lane.setdefault("result", {})
    lane["result"]["failed_at"] = now
    lane["result"]["failure_reason"] = args.reason
    common.write_lane(args.project, args.lane_id, lane)

    def _mark_failed(index):
        lane_idx = index.setdefault("lanes", {}).setdefault(args.lane_id, {})
        lane_idx["state"] = "failed"
        lane_idx["failed_at"] = now
        lane_idx["failure_reason"] = args.reason
        return index
    common.update_project_index(args.project, _mark_failed)

    memory_session = common.resolve_wakeup_target(args)
    msg = (
        f"[{args.actor}] lane_failed: {args.lane_id} "
        f"project={args.project} reason={args.reason[:120]}; "
        f"memory may re-spawn with --parent-lane {args.lane_id} + "
        f"different --model"
    )
    wakeup = common.send_wakeup(
        args.project, memory_session, msg, skip=args.skip_wakeup,
    )
    if not wakeup["ok"] and not args.skip_wakeup:
        sys.stderr.write(
            f"[deposit_asset] WARN wakeup failed: {wakeup['reason']}\n"
        )

    common.append_generation_log(args.project, {
        "event": "lane_failed",
        "lane_id": args.lane_id,
        "actor": args.actor,
        "model_asked": (lane.get("model") or None),
        "reason": args.reason,
        "wakeup_ok": wakeup["ok"],
        "wakeup_reason": wakeup["reason"],
    })

    print(args.lane_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
