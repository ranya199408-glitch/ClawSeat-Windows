#!/usr/bin/env python3
"""render_asset_tree.py — CLI view of the project asset tree.

Renders PROJECT_INDEX state as a human-readable tree (or JSON dump) so
any seat can answer "what's the current state?" without parsing the index
manually.

Default text format groups by shot_id:

    project: my-test (mode=manual, style_bible v3)
      shot-1
        lane-builder-image-abc12345 [picked] (4 candidates)
          asset-img-001 [picked] image
          asset-img-002 [deposited] image
          asset-img-003 [deposited] image
          asset-img-004 [deposited] image
      shot-2
        lane-builder-av-xyz67890 [generating]

      tournaments:
        shot-1-r1 picked=asset-img-001
      iterations:
        iter-l3-deadbeef [open] target=lane-builder-image-abc12345
      escalations:
        esc-cafebabe [open] trigger=tournament_ready_no_auto_pick_strategy

Effect
------
- Read-only — never mutates state
- Reads PROJECT_INDEX.json + lanes/*.toml
- Never reads asset content (no-image-policy)

Exit
----
- 0 on success
- 2 if --project has no PROJECT_INDEX (bootstrap not run)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_FORMATS = ("text", "json")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="render_asset_tree")
    p.add_argument("--project", required=True)
    p.add_argument("--format", default="text", choices=VALID_FORMATS)
    p.add_argument("--include-superseded", action="store_true",
                   help="Include lanes / assets in superseded state (default: hide)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    project_path = common.project_root(args.project)
    index_path = project_path / "PROJECT_INDEX.json"
    if not index_path.exists():
        sys.stderr.write(
            f"[render_asset_tree] no PROJECT_INDEX at {index_path}\n"
        )
        return 2

    index = common.load_project_index(args.project)

    tree = _build_tree(index, include_superseded=args.include_superseded)

    if args.format == "json":
        sys.stdout.write(json.dumps(tree, ensure_ascii=False, indent=2) + "\n")
    else:
        for line in _render_text(tree):
            sys.stdout.write(line + "\n")
    return 0


def _build_tree(
    index: dict[str, Any],
    *,
    include_superseded: bool,
) -> dict[str, Any]:
    lanes = dict(index.get("lanes") or {})
    assets = dict(index.get("assets") or {})

    if not include_superseded:
        lanes = {lid: l for lid, l in lanes.items() if l.get("state") != "superseded"}
        assets = {aid: a for aid, a in assets.items()
                  if a.get("status") not in ("superseded",)}

    by_shot: dict[str, dict[str, Any]] = {}
    no_shot: dict[str, Any] = {"lanes": {}, "_assets_loose": []}

    assets_by_lane: dict[str, list[str]] = {}
    for aid, a in assets.items():
        lane_id = a.get("lane")
        if lane_id:
            assets_by_lane.setdefault(lane_id, []).append(aid)

    for lid, l in lanes.items():
        shot = l.get("shot_id") or ""
        bucket = by_shot.setdefault(shot, {"lanes": {}}) if shot else no_shot
        bucket["lanes"][lid] = {
            **l,
            "assets": [
                {"asset_id": aid, **assets.get(aid, {})}
                for aid in sorted(assets_by_lane.get(lid, []))
            ],
        }

    for aid, a in assets.items():
        lane_id = a.get("lane")
        if lane_id and lane_id in lanes:
            continue
        no_shot["_assets_loose"].append({"asset_id": aid, **a})

    return {
        "project_id": index.get("project_id", ""),
        "automation_mode": index.get("automation_mode", "manual"),
        "style_bible": index.get("style_bible") or {},
        "character_dna": index.get("character_dna") or {},
        "shots": dict(sorted(by_shot.items())),
        "no_shot": no_shot if no_shot["lanes"] or no_shot["_assets_loose"] else {},
        "tournaments": dict(index.get("tournaments") or {}),
        "iterations": dict(index.get("iterations") or {}),
        "escalations": dict(index.get("escalations") or {}),
        "briefs": dict(index.get("briefs") or {}),
        "subagents": dict(index.get("subagents") or {}),
    }


def _render_text(tree: dict[str, Any]) -> list[str]:
    out: list[str] = []
    sb = tree["style_bible"]
    sb_label = (
        f"style_bible v{sb.get('version', '?')} ({sb.get('path', '')})"
        if sb.get("path") else "style_bible: unset"
    )
    out.append(
        f"project: {tree['project_id']} "
        f"(mode={tree['automation_mode']}, {sb_label})"
    )

    shots = tree["shots"]
    no_shot = tree["no_shot"]

    if not shots and not no_shot:
        out.append("  (no lanes yet)")
    else:
        for shot_id, shot in shots.items():
            out.append(f"  {shot_id or '(no shot)'}")
            _render_lanes(out, shot["lanes"], indent="    ")
        if no_shot:
            out.append("  (no shot)")
            _render_lanes(out, no_shot.get("lanes", {}), indent="    ")
            for a in no_shot.get("_assets_loose") or []:
                out.append(f"      {a['asset_id']} [{a.get('status', '?')}] "
                           f"{a.get('type', '?')} (orphan asset, no lane)")

    if tree["tournaments"]:
        out.append("")
        out.append("  tournaments:")
        for rid, r in tree["tournaments"].items():
            picked = r.get("picked") or ("[reject_all]" if r.get("rejected_all") else "[pending]")
            out.append(f"    {rid} picked={picked} ({len(r.get('candidates') or [])} candidates)")

    if tree["iterations"]:
        out.append("")
        out.append("  iterations:")
        for iid, i in tree["iterations"].items():
            target = i.get("parent_lane") or i.get("parent_shot") or i.get("target") or "?"
            out.append(f"    {iid} [{i.get('status', '?')}] {i.get('layer')} target={target}")

    if tree["escalations"]:
        out.append("")
        out.append("  escalations:")
        for eid, e in tree["escalations"].items():
            out.append(f"    {eid} [{e.get('status', '?')}] trigger={e.get('trigger')}")

    if tree["briefs"]:
        out.append("")
        out.append("  briefs:")
        for bid, b in tree["briefs"].items():
            target = b.get("target", "?")
            intent = b.get("intent", "?")
            state = b.get("state", "?")
            actor = b.get("actor", "?")
            out.append(
                f"    {bid} [{state}] target={target} intent={intent} actor={actor}"
            )

    if tree["subagents"]:
        out.append("")
        out.append("  subagents:")
        for sid, s in tree["subagents"].items():
            out.append(
                f"    {sid} [{s.get('state', '?')}] type={s.get('type', '?')} "
                f"caller={s.get('caller', '?')}"
            )

    return out


def _render_lanes(out: list[str], lanes: dict[str, Any], *, indent: str) -> None:
    for lid, lane in sorted(lanes.items()):
        seat = lane.get("seat", "?")
        state = lane.get("state", "?")
        count = lane.get("count")
        suffix = f" ({count} candidates)" if count is not None else ""
        out.append(f"{indent}{lid} [{state}] seat={seat}{suffix}")
        for a in lane.get("assets") or []:
            out.append(
                f"{indent}  {a['asset_id']} [{a.get('status', '?')}] "
                f"{a.get('type', '?')}"
            )


if __name__ == "__main__":
    sys.exit(main())
