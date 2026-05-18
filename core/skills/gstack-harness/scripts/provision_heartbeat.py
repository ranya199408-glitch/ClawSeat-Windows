#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

from _common import load_profile, materialize_profile_runtime, require_success, run_command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision heartbeat for a seat if allowed by the profile.")
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--seat", required=True, help="Seat id.")
    parser.add_argument("--force", action="store_true", help="Force reprovision when supported.")
    parser.add_argument("--dry-run", action="store_true", help="Run the underlying provision step in dry-run mode.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    if not args.dry_run:
        materialize_profile_runtime(profile)
    if args.seat not in profile.heartbeat_seats:
        print(f"heartbeat skipped: {args.seat} is not a heartbeat seat for {profile.profile_name}")
        return 0
    cmd = [
        sys.executable,
        str(profile.agent_admin),
        "session",
        "provision-heartbeat",
        args.seat,
        "--project",
        profile.project_name,
    ]
    if args.force:
        cmd.append("--force")
    if args.dry_run:
        cmd.append("--dry-run")
    result = run_command(cmd, cwd=profile.repo_root)
    require_success(result, "provision_heartbeat")
    if result.stdout.strip():
        print(result.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
