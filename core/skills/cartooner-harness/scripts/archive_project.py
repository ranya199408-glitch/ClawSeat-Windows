#!/usr/bin/env python3
"""archive_project.py — Archive a project state directory atomically.

Caller: `user` (Producer) or `memory` (Vision Steward) — typically before
a fresh protocol-test run or after a real-creative project ships.

Effect
------
- Validates the source `~/.cartooner/projects/<project>/` exists
- Generates an evidence summary (key metrics from PROJECT_INDEX +
  generation_log) into `<archived-dir>/ARCHIVE_SUMMARY.md` for future
  human / agent inspection
- Appends `project_archived` to the project's generation_log BEFORE the
  rename — so the event lives inside the archived directory itself, no
  orphan
- Renames the project dir to
  `<project>-archived-<iso>[-<reason-slug>]` to preserve evidence
- Prints the archive path to stdout

The intent (audit finding #18, 2026-05-11): protocol-test cycles
(V1 → V2 → V3) need a single primitive for "preserve evidence + clean
slate." Operators were doing this manually with `mv`, which is not
audited and easy to forget. This script makes it a one-liner that
patrol can audit.

Note: this script does NOT restart any tmux session or reseed agents.
Agent restart is a separate concern (`agent-admin window open-grid
<project> --rebuild` for iTerm refresh; `tmux kill-session` + start-project
for full agent context reset). Operator chooses whether the test calls
for a cold agent reseed or warm continuation.

Exit
----
- 0 on durable archive success (rename completed; summary + log written)
- non-zero on validation / IO failure (fail-closed; original dir
  preserved)
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_ACTORS = ("user", "memory", "memory_acting_director")
MAX_REASON_BYTES = 240


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="archive_project")
    p.add_argument("--project", required=True,
                   help="Bare project name (e.g. clawseat-storyboard-test)")
    p.add_argument("--reason", default="",
                   help="Short reason for archival (e.g. 'pre-V4-test', "
                        "'shipped to client'). Slugified into the archive "
                        "dir name suffix; preserved verbatim in the "
                        "generation_log + ARCHIVE_SUMMARY.md.")
    p.add_argument("--actor", default="user", choices=VALID_ACTORS,
                   help="Caller seat id (default: user, since archival is "
                        "typically operator-initiated)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the target archive path without performing "
                        "the rename. Generation_log is also NOT touched. "
                        "Use to preview before committing.")
    return p.parse_args(argv)


def slugify(text: str) -> str:
    """Lowercase + replace non-[a-z0-9-] with hyphens; collapse repeats."""
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")[:60]


def build_archive_name(project: str, reason: str, ts: str) -> str:
    """Compose archive directory name from project + compact ts + optional reason.

    Converts ISO ts (e.g. "2026-05-11T10:08:01.049+00:00") to a
    filesystem-friendly compact form ("20260511T100801Z") so the archive
    dir name stays scannable. Uniqueness within a second is rare; if it
    happens, main() disambiguates with a numeric suffix.
    """
    import re as _re
    # Strip non-alphanumerics, then peel back to YYYYMMDDTHHMMSS (15 chars)
    digits = _re.sub(r"[^0-9T]", "", ts)
    # "20260511T1008010490000" → take first 15 (YYYYMMDDTHHMMSS) + Z
    ts_safe = digits[:15] + "Z" if len(digits) >= 15 else digits
    base = f"{project}-archived-{ts_safe}"
    slug = slugify(reason)
    if slug:
        base += f"-{slug}"
    return base


def build_summary(index: dict, log_events: list[dict]) -> str:
    """Render a human-readable evidence summary from project state."""
    lines: list[str] = []
    lines.append(f"# Archive Summary — {index.get('project_id', '<unknown>')}")
    lines.append("")
    lines.append(f"- archived_at: {common.now_iso()}")
    lines.append(f"- automation_mode_at_archive: "
                 f"{index.get('automation_mode', '<unknown>')}")
    lines.append("")
    lines.append("## Counts")
    counts = {
        "lanes": len(index.get("lanes", {})),
        "assets": len(index.get("assets", {})),
        "briefs": len(index.get("briefs", {})),
        "tournaments": len(index.get("tournaments", {})),
        "subagents": len(index.get("subagents", {})),
        "generation_log_events": len(log_events),
    }
    for k, v in counts.items():
        lines.append(f"- {k}: {v}")
    lines.append("")

    # Lane outcome distribution
    lane_states: dict[str, int] = {}
    for lane in (index.get("lanes") or {}).values():
        st = lane.get("state", "<unknown>")
        lane_states[st] = lane_states.get(st, 0) + 1
    if lane_states:
        lines.append("## Lane outcomes")
        for st, count in sorted(lane_states.items()):
            lines.append(f"- {st}: {count}")
        lines.append("")

    # Model intent distribution (audit finding #10 audit signal)
    model_intents: dict[str, int] = {}
    fallback_count = 0
    for asset in (index.get("assets") or {}).values():
        asked = asset.get("model_asked") or "<no-intent>"
        model_intents[asked] = model_intents.get(asked, 0) + 1
        if asset.get("model_fallback_reason"):
            fallback_count += 1
    if model_intents:
        lines.append("## Asset model intent (#10 audit)")
        for m, count in sorted(model_intents.items(), key=lambda kv: -kv[1]):
            lines.append(f"- asked={m}: {count}")
        lines.append(f"- with explicit model_fallback_reason: {fallback_count}")
        lines.append("")

    # Brief outcomes
    brief_states: dict[str, int] = {}
    for brief in (index.get("briefs") or {}).values():
        st = brief.get("state", "<unknown>")
        brief_states[st] = brief_states.get(st, 0) + 1
    if brief_states:
        lines.append("## Brief outcomes")
        for st, count in sorted(brief_states.items()):
            lines.append(f"- {st}: {count}")
        lines.append("")

    # Subagent outcomes
    sa_states: dict[str, int] = {}
    for sa in (index.get("subagents") or {}).values():
        st = sa.get("state", "<unknown>")
        sa_states[st] = sa_states.get(st, 0) + 1
    if sa_states:
        lines.append("## Subagent outcomes")
        for st, count in sorted(sa_states.items()):
            lines.append(f"- {st}: {count}")
        lines.append("")

    # Key event types
    event_kinds: dict[str, int] = {}
    for ev in log_events:
        kind = ev.get("event", "<unknown>")
        event_kinds[kind] = event_kinds.get(kind, 0) + 1
    if event_kinds:
        lines.append("## generation_log event types")
        for kind, count in sorted(event_kinds.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {kind}: {count}")
        lines.append("")

    return "\n".join(lines) + "\n"


def load_generation_log(project_root: Path) -> list[dict]:
    """Read generation_log.jsonl into list-of-dicts. Tolerates missing file."""
    import json
    log_path = project_root / "generation_log.jsonl"
    if not log_path.exists():
        return []
    events: list[dict] = []
    with log_path.open(encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except Exception:
                continue
    return events


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if len(args.reason) > MAX_REASON_BYTES:
        common.fail_closed(
            f"--reason exceeds {MAX_REASON_BYTES} bytes; got {len(args.reason)}"
        )

    src_root = common.project_root(args.project)
    if not src_root.exists():
        common.fail_closed(f"project not found: {src_root}")
    if not src_root.is_dir():
        common.fail_closed(f"project path is not a directory: {src_root}")

    ts = common.now_iso()
    archive_name = build_archive_name(args.project, args.reason, ts)
    dst_root = src_root.parent / archive_name

    # Disambiguate if (extremely unlikely) collision
    suffix = 0
    while dst_root.exists():
        suffix += 1
        dst_root = src_root.parent / f"{archive_name}-{suffix}"

    if args.dry_run:
        sys.stderr.write(
            f"[archive_project] DRY RUN: would rename\n"
            f"  src: {src_root}\n"
            f"  dst: {dst_root}\n"
            f"  reason: {args.reason!r}\n"
        )
        print(str(dst_root))
        return 0

    # 1. Best-effort: write evidence summary INSIDE the source dir before
    #    rename, so it survives into the archive.
    try:
        index = common.load_project_index(args.project)
        log_events = load_generation_log(src_root)
        summary_path = src_root / "ARCHIVE_SUMMARY.md"
        summary_path.write_text(build_summary(index, log_events), encoding="utf-8")
    except Exception as exc:
        # Non-fatal — we'd rather archive without summary than fail closed
        sys.stderr.write(
            f"[archive_project] WARN summary build failed: {exc} "
            f"(archiving without summary)\n"
        )

    # 2. Append the project_archived event to the source's generation_log
    #    so the event lives inside the archived dir.
    try:
        common.append_generation_log(args.project, {
            "event": "project_archived",
            "actor": args.actor,
            "reason": args.reason or None,
            "archive_path": str(dst_root),
        })
    except Exception as exc:
        common.fail_closed(
            f"failed to write project_archived event: {exc} "
            f"(refusing to rename without audit trail)"
        )

    # 3. Atomic rename
    try:
        src_root.rename(dst_root)
    except Exception as exc:
        common.fail_closed(
            f"rename failed: {src_root} → {dst_root}: {exc}"
        )

    print(str(dst_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
