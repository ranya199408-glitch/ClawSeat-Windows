#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parents[3]
_HARNESS_SCRIPTS = _ROOT / "core" / "skills" / "gstack-harness" / "scripts"
for _path in (_HARNESS_SCRIPTS, _SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from _common import load_profile, sanitize_name  # noqa: E402


def _expand_path(value: object | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(os.path.expandvars(text)).expanduser().resolve()


def _delivery_task_id(delivery_path: Path) -> str | None:
    try:
        lines = delivery_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("task_id"):
            _, _, value = stripped.partition(":")
            value = value.strip()
            return value or None
        continue
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit planner closeout artifacts.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--task-id", required=True, help="Task id.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = load_profile(_expand_path(args.profile))
    handoff_dir = _expand_path(getattr(profile, "handoff_dir"))  # type: ignore[arg-type]
    if handoff_dir is None:
        raise SystemExit("profile missing handoff_dir")

    task_key = sanitize_name(args.task_id)
    errors: list[str] = []

    consumed_matches = list(handoff_dir.glob(f"{task_key}__*__planner.json.consumed"))
    if not consumed_matches:
        errors.append(f".consumed missing: {handoff_dir / f'{task_key}__*__planner.json.consumed'}")

    receipt_path = handoff_dir / f"{task_key}__planner__memory.json"
    if not receipt_path.is_file():
        errors.append(f"planner→memory receipt missing: {receipt_path}")

    delivery_path = Path(profile.delivery_path("planner"))  # type: ignore[attr-defined]
    actual_task_id = _delivery_task_id(delivery_path)
    if actual_task_id is None:
        errors.append(f"planner DELIVERY.md missing: {delivery_path}")
    elif actual_task_id != args.task_id:
        errors.append(
            f"planner DELIVERY.md task_id mismatch: expected {args.task_id}, got {actual_task_id}"
        )

    if errors:
        for line in errors:
            print(line)
        return 1

    print("all 3 artifacts present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
