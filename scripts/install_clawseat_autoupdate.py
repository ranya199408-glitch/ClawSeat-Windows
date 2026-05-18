#!/usr/bin/env python3
"""Install or remove the ClawSeat auto-update LaunchAgent."""

from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path
from typing import Callable, Sequence


PLIST_LABEL = "com.clawseat.autoupdate"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def log_path() -> Path:
    return Path.home() / ".clawseat" / "auto-update.log"


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(list(argv), check=False, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(list(argv), 127)


def install(
    repo: Path,
    hour: int = 3,
    minute: int = 0,
    *,
    runner: Runner = _default_runner,
) -> Path:
    repo = repo.expanduser().resolve()
    update_script = repo / "scripts" / "clawseat-update.sh"
    log = log_path()
    plist = plist_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "Label": PLIST_LABEL,
        "ProgramArguments": ["/bin/bash", str(update_script)],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "RunAtLoad": False,
    }
    with plist.open("wb") as handle:
        plistlib.dump(payload, handle)

    runner(["launchctl", "bootout", f"gui/{os.getuid()}/{PLIST_LABEL}"])
    runner(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)])
    return plist


def uninstall(*, runner: Runner = _default_runner) -> None:
    runner(["launchctl", "bootout", f"gui/{os.getuid()}/{PLIST_LABEL}"])
    plist_path().unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "uninstall"])
    parser.add_argument("--repo", default=str(Path.home() / "ClawSeat"))
    parser.add_argument("--hour", type=int, default=3)
    parser.add_argument("--minute", type=int, default=0)
    args = parser.parse_args(argv)

    if args.action == "install":
        install(Path(args.repo), hour=args.hour, minute=args.minute)
    else:
        uninstall()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
