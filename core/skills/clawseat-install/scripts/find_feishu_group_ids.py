#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT / "core" / "lib") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "core" / "lib"))
from real_home import real_user_home

OPENCLAW_HOME = Path(os.environ.get("OPENCLAW_HOME", str(real_user_home() / ".openclaw"))).expanduser()
OPENCLAW_AGENTS_ROOT = OPENCLAW_HOME / "agents"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan OpenClaw agent session stores for Feishu group ids."
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    return parser.parse_args()


def collect_group_keys(payload: Any, *, found: set[str]) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str) and key.startswith("group:"):
                found.add(key)
            collect_group_keys(value, found=found)
    elif isinstance(payload, list):
        for item in payload:
            collect_group_keys(item, found=found)


def main() -> int:
    records: list[dict[str, str]] = []
    for path in sorted(OPENCLAW_AGENTS_ROOT.glob("*/sessions/sessions.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        found: set[str] = set()
        collect_group_keys(payload, found=found)
        for key in sorted(found):
            records.append(
                {
                    "agent": path.parts[-3],
                    "group_key": key,
                    "group_id": key.split("group:", 1)[1],
                    "source": str(path),
                }
            )
    args = parse_args()
    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0
    if not records:
        print("no_group_ids_found")
        return 0
    for item in records:
        print(
            f"{item['agent']}\t{item['group_key']}\t{item['group_id']}\t{item['source']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
