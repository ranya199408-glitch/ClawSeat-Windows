#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Count closed waves since the last planner compact event.")
    parser.add_argument("--status-file", required=True, help="Path to STATUS.md.")
    parser.add_argument("--threshold", required=True, type=int, help="Wave threshold before triggering compact fallback.")
    return parser.parse_args()


def count_waves_since_compact(text: str) -> int:
    count = 0
    for line in reversed(text.splitlines()):
        if "compacted planner" in line:
            break
        if "phase=CLOSED" in line:
            count += 1
    return count


def main() -> int:
    args = parse_args()
    path = Path(args.status_file).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    waves_since = count_waves_since_compact(text)
    triggered = waves_since >= args.threshold
    print(f"triggered={'true' if triggered else 'false'} waves_since={waves_since}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
