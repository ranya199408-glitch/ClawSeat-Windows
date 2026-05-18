#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


MARKER = "[memory: compact-me]"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check whether a relay text includes the memory compact marker.")
    parser.add_argument("--relay-text-file", help="Path to a relay text file.")
    parser.add_argument("--text", help="Inline relay text.")
    return parser.parse_args()


def load_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.relay_text_file:
        path = Path(args.relay_text_file).expanduser()
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""
    return ""


def main() -> int:
    args = parse_args()
    text = load_text(args)
    print(f"marker={'present' if MARKER in text else 'absent'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
