#!/usr/bin/env python3
"""Install or remove patrol cron entries."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

MARKER = "# ClawSeat patrol"
SCRIPT = Path(__file__).resolve().with_name("patrol_cron.sh")


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    return "" if result.returncode != 0 else result.stdout


def _write_crontab(text: str) -> None:
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)


def remove_entry(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skip = 0
    for line in lines:
        if skip:
            skip -= 1
            continue
        if line == MARKER:
            skip = 2
            continue
        kept.append(line)
    return "\n".join(kept).rstrip() + ("\n" if kept else "")


def install() -> None:
    current = remove_entry(_current_crontab()).rstrip()
    entry = "\n".join([
        MARKER,
        f"0 3 * * * {SCRIPT} daily",
        f"0 3 * * 0 {SCRIPT} weekly",
    ])
    _write_crontab((current + "\n\n" + entry + "\n").lstrip())


def uninstall() -> None:
    _write_crontab(remove_entry(_current_crontab()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall"])
    args = parser.parse_args()
    if args.action == "install":
        install()
    else:
        uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
