#!/usr/bin/env python3
"""pick_winner.py — Record a tournament pick into project state.

Backend-only. The UI for showing candidates to user and collecting the
choice is the caller's responsibility:

  - Manual mode (memory in Claude Code): use Claude Code's native
    `AskUserQuestion` tool to display candidate metadata + "Reject all".
    Pass user's choice as --picked or --reject-all.
  - Auto mode (memory in auto + model-metadata-rank): no UI; this script
    ranks candidates by model_metadata.aesthetic_score.

See `references/automation-mode.md` for strategy details.

Effect
------
- Validates candidates exist + come from same shot_id (cross-modal coherence)
- Writes tournaments/<round-id>.toml
- Updates PROJECT_INDEX.tournaments[<round-id>]
- Marks winner's asset (status=picked) + lane (state=picked)
- Appends generation_log (event=pick_winner)
- Prints winner asset_id to stdout (empty for reject_all)

Exit
----
- 0 on success
- non-zero on validation / state failure (fail-closed)
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_STRATEGIES = (
    "manual",
    "model-metadata-rank",
    "first-passing",
    "random-from-passing",
)
VALID_PICKERS = ("user", "memory_acting_director")
VALID_PICK_METHODS = (
    # Trust-aware pick provenance, surfaced after 2026-05-11 audit finding
    # #4 (cross-session AskUserQuestion answered by non-producer entity).
    # Without this field, pick_winner records actor=user and an audit
    # reader cannot tell whether the producer truly attested or whether
    # some autopilot / sandbox default supplied the answer.
    "external_signed_token",      # producer ack via send-and-verify or out-of-band signature; strongest trust
    "native_ask_user_question",   # native UI in the calling seat's tool (Claude Code AskUserQuestion / Codex prompt) — TRUST DEPENDS ON SESSION ATTACHMENT
    "memory_default_no_ack",      # memory autopicked because no producer was reachable; weakest trust, must be flagged
    "auto_strategy",              # one of model-metadata-rank / first-passing / random-from-passing fired with no producer in the loop
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pick_winner")
    p.add_argument("--project", required=True)
    p.add_argument("--round-id", required=True,
                   help="Tournament round id, e.g. shot-1-r1")
    p.add_argument("--candidates", required=True,
                   help="Comma-separated asset ids in this round")
    p.add_argument("--strategy", default="manual", choices=VALID_STRATEGIES)
    p.add_argument("--picked", default="",
                   help="(strategy=manual) winner asset_id; must be in --candidates")
    p.add_argument("--reject-all", action="store_true",
                   help="Mark tournament rejected; no winner; downstream iterates or pauses")
    p.add_argument("--min-score", type=float, default=0.75,
                   help="(model-metadata-rank) min aesthetic_score threshold; below = no auto-pick")
    p.add_argument("--picker", default="user", choices=VALID_PICKERS,
                   help="user (manual) or memory_acting_director (auto mode)")
    p.add_argument("--pick-method", default="", choices=("",) + VALID_PICK_METHODS,
                   help="Trust-aware provenance of how the pick was reached. "
                        "REQUIRED when --picker user (audit needs to know "
                        "whether the producer truly attested or whether a "
                        "tool-level UI / autopilot supplied the answer). "
                        "Memory-driven auto picks default to 'auto_strategy'.")
    p.add_argument("--reason", default="",
                   help="Optional human-readable reason for the pick")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    common.validate_id_token(args.round_id, kind="--round-id")

    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    if not candidates:
        common.fail_closed("--candidates must be non-empty")
    if len(set(candidates)) != len(candidates):
        common.fail_closed(f"--candidates contains duplicates: {candidates}")
    for c in candidates:
        common.validate_id_token(c, kind="--candidates element")

    if args.reject_all and args.picked:
        common.fail_closed("--reject-all and --picked are mutually exclusive")

    # Resolve trust-aware pick_method (audit finding #4):
    # picker=user without explicit pick_method is now ambiguous, because
    # native_ask_user_question may be answered by an autopilot rather
    # than the actual producer. Force the caller to be explicit so the
    # generation_log carries the trust signal forward.
    pick_method = args.pick_method
    if not pick_method:
        if args.strategy == "manual" and args.picker == "user":
            common.fail_closed(
                "--pick-method is REQUIRED when --picker user "
                "(audit finding #4). Choose one of: "
                f"{', '.join(VALID_PICK_METHODS)}"
            )
        if args.strategy == "manual" and args.picker == "memory_acting_director":
            pick_method = "memory_default_no_ack"
        else:
            pick_method = "auto_strategy"

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)
    assets = index.setdefault("assets", {})

    missing = [c for c in candidates if c not in assets]
    if missing:
        common.fail_closed(f"candidates not in PROJECT_INDEX.assets: {missing}")

    # cross-shot coherence: all candidates must share the same shot_id
    candidate_shots: set[str] = set()
    for c in candidates:
        lane_id = assets[c].get("lane")
        if not lane_id:
            common.fail_closed(f"asset {c} missing lane reference")
        lane_data = common.load_lane(args.project, lane_id)
        if lane_data is not None:
            candidate_shots.add(lane_data.get("shot_id") or "")
    if len(candidate_shots) > 1:
        common.fail_closed(
            f"candidates span multiple shots: {sorted(candidate_shots)}; tournament must be per-shot"
        )

    # idempotency: if round already picked, only allow same-winner re-call
    tournaments = index.setdefault("tournaments", {})
    existing = tournaments.get(args.round_id)
    if existing and existing.get("picked"):
        if args.picked and existing["picked"] != args.picked:
            common.fail_closed(
                f"round {args.round_id} already picked={existing['picked']!r}; "
                f"cannot re-pick to {args.picked!r}"
            )
        if args.reject_all:
            common.fail_closed(
                f"round {args.round_id} already picked={existing['picked']!r}; cannot reject_all"
            )

    winner = _decide_winner(args, candidates, assets)

    now = common.now_iso()
    record: dict = {
        "round_id": args.round_id,
        "candidates": candidates,
        "picked": winner or "",
        "rejected_all": bool(args.reject_all),
        "strategy": args.strategy,
        "picker": args.picker,
        "pick_method": pick_method,
        "reason": args.reason,
        "decided_at": now,
    }

    # tournament TOML
    tournament_dir = common.project_root(args.project) / "tournaments"
    tournament_dir.mkdir(parents=True, exist_ok=True)
    tournament_path = tournament_dir / f"{args.round_id}.toml"
    tournament_path.write_text(common.serialize_toml(record), encoding="utf-8")

    tournaments[args.round_id] = record

    if winner is not None:
        assets[winner]["status"] = "picked"
        assets[winner]["picked_at"] = now
        winner_lane_id = assets[winner].get("lane")
        if winner_lane_id and winner_lane_id in index.setdefault("lanes", {}):
            index["lanes"][winner_lane_id]["state"] = "picked"
            index["lanes"][winner_lane_id]["picked_at"] = now
        if winner_lane_id:
            lane_file = common.load_lane(args.project, winner_lane_id)
            if lane_file is not None:
                lane_file["state"] = "picked"
                lane_file.setdefault("result", {})["picked"] = winner
                lane_file["result"]["picked_at"] = now
                common.write_lane(args.project, winner_lane_id, lane_file)

    common.write_project_index(args.project, index)

    common.append_generation_log(args.project, {
        "event": "pick_winner",
        "round_id": args.round_id,
        "candidates": candidates,
        "picked": winner,
        "rejected_all": bool(args.reject_all),
        "strategy": args.strategy,
        "actor": args.picker,
        "pick_method": pick_method,
        "reason": args.reason or None,
    })

    print(winner if winner else "")
    return 0


def _decide_winner(
    args: argparse.Namespace,
    candidates: list[str],
    assets: dict,
) -> str | None:
    if args.reject_all:
        return None

    if args.strategy == "manual":
        if not args.picked:
            common.fail_closed("--strategy manual requires --picked or --reject-all")
        if args.picked not in candidates:
            common.fail_closed(f"--picked {args.picked!r} not in --candidates")
        return args.picked

    if args.strategy == "model-metadata-rank":
        ranked: list[tuple[float, str]] = []
        for c in candidates:
            score = assets[c].get("model_metadata", {}).get("aesthetic_score")
            if score is None:
                continue
            ranked.append((float(score), c))
        if not ranked:
            common.fail_closed(
                "model-metadata-rank: no candidate has aesthetic_score; cannot auto-pick"
            )
        ranked.sort(reverse=True)
        best_score, best_id = ranked[0]
        if best_score < args.min_score:
            common.fail_closed(
                f"model-metadata-rank: best score {best_score} below --min-score {args.min_score}"
            )
        return best_id

    if args.strategy == "first-passing":
        return candidates[0]

    if args.strategy == "random-from-passing":
        return secrets.choice(candidates)

    common.fail_closed(f"unknown strategy: {args.strategy}")  # pragma: no cover
    return None  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
