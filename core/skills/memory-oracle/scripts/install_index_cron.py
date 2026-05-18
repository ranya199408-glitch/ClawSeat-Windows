#!/usr/bin/env python3
"""Install or remove the Memory index rebuild cron entry."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


MARKER = "# ClawSeat memory index rebuild"
CRON_SCRIPT = Path(__file__).resolve().with_name("rebuild_index_cron.sh")


def _current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    return "" if result.returncode != 0 else result.stdout


def _write_crontab(text: str) -> None:
    subprocess.run(["crontab", "-"], input=text, text=True, check=True)


def install() -> None:
    current = _remove_entry(_current_crontab())
    entry = f"{MARKER}\n0 3 * * * {CRON_SCRIPT}\n"
    _write_crontab((current.rstrip() + "\n\n" + entry).lstrip())


def uninstall() -> None:
    _write_crontab(_remove_entry(_current_crontab()))


def _remove_entry(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        if line == MARKER:
            skip_next = True
            continue
        kept.append(line)
    return "\n".join(kept).rstrip() + ("\n" if kept else "")


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
