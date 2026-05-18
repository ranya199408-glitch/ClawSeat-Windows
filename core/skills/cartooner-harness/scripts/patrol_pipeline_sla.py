#!/usr/bin/env python3
"""patrol_pipeline_sla.py — Pipeline SLA + integrity + skill-authorization audit.

Caller: `patrol` (read-only Asset Guardian seat). Mutates nothing.

Three independent check families, each runnable alone or in combination:

sla
---
- Scan PROJECT_INDEX.lanes for state in (spawned, generating)
- Flag any older than --sla-threshold-mins (default 30)
- Reasoning: a lane stuck in spawned/generating means the target seat
  failed to deposit; auto mode should escalate, manual mode should alert

integrity
---------
- For each asset in PROJECT_INDEX.assets, verify path exists + file size
  matches recorded `file_size`
- For each lane in PROJECT_INDEX.lanes, verify lanes/<lane-id>.toml exists
- Never reads asset content (no-image-policy); only stat()

authorization
-------------
- Scan generation_log.jsonl for events whose actor doesn't match the
  protocol's seat-operation matrix (e.g. `writer` calling spawn_lane,
  `patrol` calling pick_winner, `builder-image` depositing video)
- Cross-references the matrix in cartooner-harness/SKILL.md
- Soft enforcement: emits a report; v1 doesn't block

Exit
----
- 0 if --check passed (no anomalies)
- 2 if anomalies detected (so callers / CI can branch on it)
- 1 on validation / read failure (fail-closed)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_CHECKS = ("sla", "integrity", "authorization", "all")
VALID_FORMATS = ("text", "json")

# Operation-level authorization (which seat may emit which event).
# Mirrors SKILL.md "Skill Authorization Matrix" and per-seat user-direct
# table; this is the audit ground truth.
EVENT_ALLOWED_ACTORS: dict[str, set[str]] = {
    "lane_spawned": {"memory", "builder-image", "builder-av", "writer"},
    "asset_deposited": {"builder-image", "builder-av", "writer"},
    "lane_failed": {"builder-image", "builder-av", "writer"},
    # audit finding #18 (2026-05-11): project_archived is the audited
    # state-archive primitive (replaces operator-side `mv ...` which had
    # no audit trail). Actor is typically user (Producer-initiated)
    # but memory may also invoke (e.g., automation policy archiving
    # stale tests).
    "project_archived": {"user", "memory", "memory_acting_director"},
    "pick_winner": {"user", "memory_acting_director"},
    "iterate_prompt": {"user", "memory_acting_director"},
    "share_style_bible": {"user", "memory_acting_director"},
    "set_automation_mode": {"user", "memory_acting_director"},
    "escalate_to_producer": {"memory_acting_director", "patrol"},
    # report_to_memory uses "actor=triggered_by" so it can be user / memory / patrol
    "user_direct_request": {"user"},
    "lane_completed": {"user", "memory", "patrol", "builder-image", "builder-av", "writer"},
    "shot_list_revised": {"user", "memory", "writer", "builder-av"},
    "shot_list_authored": {"user", "memory", "writer", "builder-av"},
    # memory_internal_note (audit finding #1) — sanctioned free-form
    # coordination channel; only memory-side actors. Patrol previously
    # had to flag any non-protocol log entry as anomalous; this gives
    # memory a typed home so its honest internal notes don't trip audit.
    "memory_internal_note": {"memory", "memory_acting_director"},
    "subagent_started": {"builder-image", "builder-av"},
    "subagent_spawned": {"builder-image", "builder-av"},
    "subagent_completed": {"builder-image", "builder-av"},
    "subagent_failed": {"builder-image", "builder-av"},
    # cross-seat dispatch protocol (communication-protocol.md §6).
    # brief_dispatched normally has actor=memory, but user-direct
    # self-dispatch sets actor=<seat> + triggered_by=user_direct (enforced
    # by dispatch_brief.py to also require target == actor). Patrol's
    # actor allowlist is the union; refining cross-condition rules belongs
    # in a separate brief-specific check.
    "brief_dispatched": {"memory", "writer", "builder-image", "builder-av"},
    "brief_delivered": {"writer", "builder-image", "builder-av"},
    "brief_failed": {"writer", "builder-image", "builder-av"},
}

ASSET_TYPE_BY_ACTOR: dict[str, set[str]] = {
    "builder-image": {"image"},
    "builder-av": {"video", "audio"},
    "writer": {"text"},
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="patrol_pipeline_sla")
    p.add_argument("--project", required=True)
    p.add_argument("--check", default="all", choices=VALID_CHECKS)
    p.add_argument("--sla-threshold-mins", type=float, default=30.0)
    p.add_argument("--format", default="text", choices=VALID_FORMATS)
    p.add_argument("--exit-zero-on-anomaly", action="store_true",
                   help="Always exit 0 even if anomalies found (use when invoked by "
                        "memory which logs results without aborting flow)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    project_path = common.project_root(args.project)
    if not (project_path / "PROJECT_INDEX.json").exists():
        sys.stderr.write(f"[patrol] no PROJECT_INDEX at {project_path}\n")
        return 1

    index = common.load_project_index(args.project)

    report: dict[str, Any] = {
        "project": args.project,
        "checked_at": common.now_iso(),
        "checks_run": [],
        "anomalies": [],
    }

    if args.check in ("sla", "all"):
        report["checks_run"].append("sla")
        report["anomalies"].extend(
            _check_sla(args.project, index, args.sla_threshold_mins)
        )

    if args.check in ("integrity", "all"):
        report["checks_run"].append("integrity")
        report["anomalies"].extend(_check_integrity(args.project, index))

    if args.check in ("authorization", "all"):
        report["checks_run"].append("authorization")
        report["anomalies"].extend(_check_authorization(args.project))

    if args.format == "json":
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        for line in _render_text(report):
            sys.stdout.write(line + "\n")

    if report["anomalies"] and not args.exit_zero_on_anomaly:
        return 2
    return 0


def _check_sla(
    project: str,
    index: dict[str, Any],
    threshold_mins: float,
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    now = datetime.now(tz=None).astimezone()

    def _age_check(
        kind: str,
        item_id: str,
        created: str | None,
        state: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not created:
            anomalies.append({
                "check": "sla",
                "severity": "warn",
                f"{kind}_id": item_id,
                "reason": f"{kind} has no created_at; cannot age-check",
            })
            return
        try:
            ts = datetime.fromisoformat(created)
            if ts.tzinfo is None:
                ts = ts.astimezone()
        except ValueError:
            anomalies.append({
                "check": "sla",
                "severity": "warn",
                f"{kind}_id": item_id,
                "reason": f"{kind} has invalid created_at: {created!r}",
            })
            return
        age_mins = (now - ts).total_seconds() / 60.0
        if age_mins > threshold_mins:
            entry: dict[str, Any] = {
                "check": "sla",
                "severity": "alert",
                f"{kind}_id": item_id,
                "state": state,
                "age_mins": round(age_mins, 1),
                "threshold_mins": threshold_mins,
                "reason": f"{kind} stuck in state={state} for {age_mins:.1f} min "
                          f"(> threshold {threshold_mins} min)",
            }
            if extra:
                entry.update(extra)
            anomalies.append(entry)

    for lane_id, lane in (index.get("lanes") or {}).items():
        state = lane.get("state")
        if state not in ("spawned", "generating"):
            continue
        _age_check("lane", lane_id, lane.get("created_at"), state)

    for brief_id, brief in (index.get("briefs") or {}).items():
        state = brief.get("state")
        if state != "open":
            continue
        _age_check("brief", brief_id, brief.get("created_at"), state, extra={
            "target": brief.get("target"),
            "intent": brief.get("intent"),
        })

    for sa_id, sa in (index.get("subagents") or {}).items():
        state = sa.get("state")
        if state != "spawned":
            continue
        _age_check("subagent", sa_id, sa.get("spawned_at"), state, extra={
            "caller": sa.get("caller"),
            "subagent_type": sa.get("type"),
        })

    return anomalies


def _check_integrity(project: str, index: dict[str, Any]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    project_path = common.project_root(project)

    for asset_id, asset in (index.get("assets") or {}).items():
        path_str = asset.get("path")
        if not path_str:
            anomalies.append({
                "check": "integrity",
                "severity": "alert",
                "asset_id": asset_id,
                "reason": "asset has no path field",
            })
            continue
        path = Path(path_str)
        if not path.exists():
            anomalies.append({
                "check": "integrity",
                "severity": "alert",
                "asset_id": asset_id,
                "path": path_str,
                "reason": "asset file missing on disk",
            })
            continue
        if not path.is_file():
            anomalies.append({
                "check": "integrity",
                "severity": "alert",
                "asset_id": asset_id,
                "path": path_str,
                "reason": "asset path is not a regular file",
            })
            continue
        recorded_size = asset.get("file_size")
        actual_size = path.stat().st_size
        if recorded_size is not None and recorded_size != actual_size:
            anomalies.append({
                "check": "integrity",
                "severity": "warn",
                "asset_id": asset_id,
                "path": path_str,
                "recorded_size": recorded_size,
                "actual_size": actual_size,
                "reason": "asset file size differs from recorded value",
            })

    for lane_id in (index.get("lanes") or {}).keys():
        lane_path = project_path / "lanes" / f"{lane_id}.toml"
        if not lane_path.exists():
            anomalies.append({
                "check": "integrity",
                "severity": "alert",
                "lane_id": lane_id,
                "reason": "lane TOML missing on disk (PROJECT_INDEX out of sync)",
            })
    return anomalies


def _check_authorization(project: str) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    log_path = common.project_root(project) / "generation_log.jsonl"
    if not log_path.exists():
        return anomalies

    with log_path.open(encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as e:
                anomalies.append({
                    "check": "authorization",
                    "severity": "warn",
                    "line": line_no,
                    "reason": f"unparseable generation_log line: {e}",
                })
                continue

            ev_name = event.get("event")
            actor = event.get("actor")
            allowed = EVENT_ALLOWED_ACTORS.get(ev_name)
            if allowed is not None and actor and actor not in allowed:
                anomalies.append({
                    "check": "authorization",
                    "severity": "alert",
                    "line": line_no,
                    "event": ev_name,
                    "actor": actor,
                    "allowed": sorted(allowed),
                    "reason": f"actor {actor!r} not authorized for event {ev_name!r}",
                })

            if ev_name == "asset_deposited":
                asset_type = event.get("asset_type")
                allowed_types = ASSET_TYPE_BY_ACTOR.get(actor or "", set())
                if asset_type and asset_type not in allowed_types:
                    anomalies.append({
                        "check": "authorization",
                        "severity": "alert",
                        "line": line_no,
                        "event": ev_name,
                        "actor": actor,
                        "asset_type": asset_type,
                        "reason": f"actor {actor!r} not authorized for asset_type "
                                  f"{asset_type!r}",
                    })

            # Hub-and-spoke cross-field check (communication-protocol.md §7):
            # brief_dispatched with non-memory actor is only legitimate when
            # triggered_by=user_direct (Producer override per §8). Anything
            # else is a lateral seat-to-seat dispatch and a protocol breach.
            if ev_name == "brief_dispatched" and actor and actor != "memory":
                if event.get("triggered_by") != "user_direct":
                    anomalies.append({
                        "check": "authorization",
                        "severity": "alert",
                        "line": line_no,
                        "event": ev_name,
                        "actor": actor,
                        "reason": f"non-memory actor {actor!r} dispatched a brief "
                                  f"without --triggered-by user_direct "
                                  f"(hub-and-spoke violation)",
                    })

            # pick_winner trust-chain check (audit finding #4):
            # actor=user with weak pick_method is suspicious — the producer
            # may not have actually attested. Surface as warning so audit
            # readers can investigate (and so memory cannot silently pass
            # off autopilot answers as producer decisions).
            if ev_name == "pick_winner" and actor == "user":
                pm = event.get("pick_method")
                if pm in (None, "memory_default_no_ack", "auto_strategy"):
                    anomalies.append({
                        "check": "authorization",
                        "severity": "alert",
                        "line": line_no,
                        "event": ev_name,
                        "actor": actor,
                        "reason": f"actor=user with pick_method={pm!r}; "
                                  f"trust chain broken (producer did not attest)",
                    })
                elif pm == "native_ask_user_question":
                    anomalies.append({
                        "check": "authorization",
                        "severity": "warn",
                        "line": line_no,
                        "event": ev_name,
                        "actor": actor,
                        "reason": "actor=user with pick_method=native_ask_user_question; "
                                  "trust depends on session attachment (verify producer truly answered)",
                    })
    return anomalies


def _render_text(report: dict[str, Any]) -> list[str]:
    out: list[str] = []
    out.append(
        f"patrol report — project={report['project']} "
        f"checked_at={report['checked_at']}"
    )
    out.append(f"  checks: {', '.join(report['checks_run'])}")
    anomalies = report["anomalies"]
    if not anomalies:
        out.append("  result: clean (no anomalies)")
        return out
    out.append(f"  result: {len(anomalies)} anomalies")
    for a in anomalies:
        check = a.get("check", "?")
        sev = a.get("severity", "?")
        reason = a.get("reason", "?")
        loc_bits: list[str] = []
        for k in ("lane_id", "asset_id", "brief_id", "subagent_id", "line", "event", "actor"):
            v = a.get(k)
            if v is not None:
                loc_bits.append(f"{k}={v}")
        loc = " ".join(loc_bits) if loc_bits else ""
        out.append(f"    [{sev}] {check}: {reason} {loc}".rstrip())
    return out


if __name__ == "__main__":
    sys.exit(main())
