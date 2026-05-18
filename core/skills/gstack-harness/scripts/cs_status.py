#!/usr/bin/env python3
"""cs_status — read-only operator observability for seat task state.

Usage:
  python3 cs_status.py --profile PROFILE
  python3 cs_status.py --profile PROFILE --seat builder-1
  python3 cs_status.py --profile PROFILE --correlation-id afd10484
  python3 cs_status.py --profile PROFILE --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _common import load_profile

# ── Parsing ───────────────────────────────────────────────────────────────────

_BLOCK_SPLIT_RE = re.compile(r"(?m)^(?=## \[)")
_HEADER_RE = re.compile(r"^## \[(pending|queued|in_progress|completed|abandoned)\] (.+)$")
_FIELD_RE = re.compile(r"^(\w[\w_-]*): (.+)$")

_ACTIVE_STATUSES = {"pending", "queued"}


def _parse_task_blocks(text: str) -> list[dict]:
    """Return a list of dicts, one per task block in a TODO.md."""
    rows: list[dict] = []
    for block in _BLOCK_SPLIT_RE.split(text):
        header_match = _HEADER_RE.match(block.splitlines()[0]) if block.strip() else None
        if not header_match:
            continue
        status = header_match.group(1)
        fields: dict = {"status": status}
        for line in block.splitlines()[1:]:
            m = _FIELD_RE.match(line)
            if m:
                fields[m.group(1)] = m.group(2).strip()
            elif line.startswith("###"):
                break
        rows.append(fields)
    return rows


def _load_receipts(handoff_dir: Path) -> list[dict]:
    """Load all JSON receipt files from handoff_dir. Silently skip malformed."""
    receipts: list[dict] = []
    if not handoff_dir.is_dir():
        return receipts
    for p in handoff_dir.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if isinstance(data, dict):
                receipts.append(data)
        except (json.JSONDecodeError, OSError):  # silent-ok: corrupt/missing receipt, skip
            pass
    return receipts


def _age_str(dispatched_at: str | None) -> str:
    """Return human-readable age string from ISO timestamp, or '-'."""
    if not dispatched_at:
        return "-"
    try:
        dt = datetime.fromisoformat(dispatched_at.replace("Z", "+00:00"))
        delta = datetime.now(tz=timezone.utc) - dt
        total = int(delta.total_seconds())
        if total < 3600:
            return f"{total // 60}m"
        if total < 86400:
            return f"{total // 3600}h"
        return f"{total // 86400}d"
    except (ValueError, TypeError):  # silent-ok: unparseable timestamp, render '-'
        return "-"


# ── State resolution ──────────────────────────────────────────────────────────

def _resolve_state(task_id: str, seat: str, receipts: list[dict]) -> str:
    """Classify task state for a given seat using receipt evidence.

    queued   — TODO has entry, no matching dispatch receipt found yet
    in-flight — dispatch receipt exists (kind=dispatch, target=seat), no completion
    delivered — completion receipt exists (kind=completion, source=seat)
    """
    has_dispatch = any(
        r.get("kind") == "dispatch"
        and r.get("task_id") == task_id
        and r.get("target") == seat
        for r in receipts
    )
    has_completion = any(
        r.get("kind") == "completion"
        and r.get("task_id") == task_id
        and r.get("source") == seat
        for r in receipts
    )
    if has_completion:
        return "delivered"
    if has_dispatch:
        return "in-flight"
    return "queued"


# ── Data collection ───────────────────────────────────────────────────────────

def collect_rows(profile, seat_filter: str | None = None, cid_filter: str | None = None) -> list[dict]:
    """Return status rows for all active tasks across all (filtered) seats."""
    receipts = _load_receipts(profile.handoff_dir)
    seats = [seat_filter] if seat_filter else profile.seats
    rows: list[dict] = []
    for seat in seats:
        todo_path = profile.todo_path(seat)
        if not todo_path.exists():
            continue
        try:
            text = todo_path.read_text()
        except OSError:  # silent-ok: unreadable TODO, skip seat
            continue
        for block in _parse_task_blocks(text):
            if block.get("status") not in _ACTIVE_STATUSES:
                continue
            task_id = block.get("task_id", "")
            correlation_id = block.get("correlation_id", "-")
            if cid_filter and correlation_id != cid_filter:
                continue
            state = _resolve_state(task_id, seat, receipts)
            rows.append({
                "seat": seat,
                "task_id": task_id,
                "correlation_id": correlation_id,
                "state": state,
                "dispatched_at": block.get("dispatched_at", ""),
                "age": _age_str(block.get("dispatched_at")),
                "title": block.get("title", ""),
                "source": block.get("source", ""),
                "target": seat,
            })
    return rows


# ── Output formatters ─────────────────────────────────────────────────────────

def _fmt_table(rows: list[dict]) -> str:
    if not rows:
        return "(no active tasks)"
    cols = ["seat", "task_id", "correlation_id", "state", "dispatched_at", "age"]
    header = "  ".join(f"{c:<20}" if c not in ("state", "age", "correlation_id") else f"{c:<12}" for c in cols)
    lines = [header, "-" * len(header)]
    for r in rows:
        parts = []
        for c in cols:
            val = r.get(c, "-") or "-"
            width = 12 if c in ("state", "age", "correlation_id") else 20
            parts.append(f"{val:<{width}}")
        lines.append("  ".join(parts))
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only seat task status query.")
    parser.add_argument("--profile", required=True, help="Path to project profile TOML.")
    parser.add_argument("--seat", help="Filter to a single seat (e.g. builder-1).")
    parser.add_argument("--correlation-id", dest="correlation_id", help="Filter by 8-hex correlation_id.")
    parser.add_argument("--json", dest="emit_json", action="store_true", help="Emit JSON instead of text table.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    rows = collect_rows(profile, seat_filter=args.seat, cid_filter=args.correlation_id)
    if args.emit_json:
        # Map '-' sentinel (text-table only) to None for machine-readable output.
        json_rows = [{**r, "correlation_id": r["correlation_id"] if r["correlation_id"] != "-" else None} for r in rows]
        print(json.dumps(json_rows, ensure_ascii=False, indent=2))
    else:
        print(_fmt_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
