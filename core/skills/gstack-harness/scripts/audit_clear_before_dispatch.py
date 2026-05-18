#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_scripts_dir = Path(__file__).parent.resolve()
_core_lib = _scripts_dir.parent.parent.parent / "lib"
if str(_core_lib) not in sys.path:
    sys.path.insert(0, str(_core_lib))

from _common import load_json, load_profile, resolve_session_name, sanitize_name


BUSY_MARKERS = ("Working", "Thinking", "Spinning", "Misting", "• ", "background terminal running")


def _required(value: str | None, env_name: str, parser: argparse.ArgumentParser, label: str) -> str:
    value = (value or os.environ.get(env_name, "")).strip()
    if value:
        return value
    parser.error(f"--{label} (or {env_name}) is required")


def _latest_consumed_receipt(profile: object, target: str) -> tuple[str | None, Path | None]:
    handoff_dir = Path(str(getattr(profile, "handoff_dir"))).expanduser().resolve()
    pattern = f"*__{sanitize_name(target)}__planner.json.consumed"
    candidates = [path for path in handoff_dir.glob(pattern) if path.is_file()]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates:
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        if payload.get("kind") != "completion" or payload.get("source") != target or payload.get("target") != "planner":
            continue
        task_id = str(payload.get("task_id") or path.name.split("__", 1)[0]).strip() or None
        return task_id, path
    return None, None


def _capture_tail(session_name: str, lines: int) -> tuple[str | None, str | None]:
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, (result.stderr.strip() or result.stdout.strip() or f"capture-pane rc={result.returncode}")
    tail = "\n".join(result.stdout.splitlines()[-lines:]).strip()
    return tail, None


def _pane_idle(tail: str) -> tuple[bool, str]:
    if not tail:
        return True, "idle"
    if "background terminal running" in tail:
        return False, "background terminal running"
    for marker in BUSY_MARKERS:
        if marker in tail:
            return False, marker
    return True, "idle"


def _clear_seen(tail: str) -> bool:
    return any(line.strip().startswith("/clear") or " /clear" in line for line in tail.splitlines())


def _parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(description="Audit planner /clear-before-dispatch protocol.")
    parser.add_argument("--profile", help="Path to the project profile TOML.")
    parser.add_argument("--task-id", help="Current task id being dispatched.")
    parser.add_argument("--target", help="Target worker seat.")
    parser.add_argument(
        "--lookback-lines",
        type=int,
        default=int(os.environ.get("CLEAR_AUDIT_LOOKBACK_LINES", "12")),
        help="Recent pane lines to inspect for a /clear command.",
    )
    return parser, parser.parse_args()


def main() -> int:
    parser, args = _parse_args()
    profile = load_profile(_required(args.profile, "CLEAR_AUDIT_PROFILE", parser, "profile"))
    task_id = _required(args.task_id, "CLEAR_AUDIT_TASK_ID", parser, "task-id")
    target = _required(args.target, "CLEAR_AUDIT_TARGET", parser, "target")

    prev_task, receipt_path = _latest_consumed_receipt(profile, target)
    delivery_path = profile.delivery_path(target)
    if receipt_path is None or not delivery_path.exists():
        print(
            f"clear-audit: skip task_id={task_id} target={target} reason=gate1_missing "
            f"prev_task={prev_task or '<none>'} delivery={delivery_path.exists()} receipt={bool(receipt_path)}",
            file=sys.stderr,
        )
        return 2

    session_name = resolve_session_name(profile, target)
    tail, error = _capture_tail(session_name, args.lookback_lines)
    if error:
        print(
            f"clear-audit: skip task_id={task_id} target={target} reason=gate3_unavailable "
            f"session={session_name} detail={error}",
            file=sys.stderr,
        )
        return 2

    idle, reason = _pane_idle(tail or "")
    if not idle:
        print(
            f"clear-audit: skip task_id={task_id} target={target} reason=gate3_busy "
            f"session={session_name} detail={reason}",
            file=sys.stderr,
        )
        return 2

    if not _clear_seen(tail or ""):
        print(
            f"[CLEAR-AUDIT-WARNING] task_id={task_id} target={target} prev_task={prev_task or '<none>'} "
            f"session={session_name} clear not seen in last {args.lookback_lines} lines",
            file=sys.stderr,
        )
        return 1

    print(f"clear-audit: pass task_id={task_id} target={target} prev_task={prev_task or '<none>'} session={session_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
