#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _common import load_profile, load_toml, utc_now_iso, write_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a durable receipt that a seat has re-read its workspace contract."
    )
    parser.add_argument("--profile", required=True, help="Path to the project profile TOML.")
    parser.add_argument("--seat", required=True, help="Seat id.")
    parser.add_argument(
        "--ack-source",
        default="seat-self-check",
        help="Who is asserting the reread (seat-self-check, operator, hook, etc).",
    )
    parser.add_argument(
        "--note",
        default="Workspace guide and WORKSPACE_CONTRACT.toml re-read.",
        help="Short note describing the acknowledgement.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = load_profile(args.profile)
    workspace = profile.workspace_for(args.seat)
    contract_path = workspace / "WORKSPACE_CONTRACT.toml"
    if not contract_path.exists():
        raise SystemExit(f"missing workspace contract: {contract_path}")
    contract = load_toml(contract_path) or {}
    contract_fingerprint = str(contract.get("contract_fingerprint", "")).strip()
    if not contract_fingerprint:
        raise SystemExit(f"workspace contract missing contract_fingerprint: {contract_path}")
    receipt_path = workspace / "WORKSPACE_CONTRACT_RECEIPT.toml"
    lines = [
        "version = 1",
        f'seat_id = "{args.seat}"',
        f'project = "{profile.project_name}"',
        f'role = "{profile.seat_roles.get(args.seat, "")}"',
        f'contract_path = "{contract_path}"',
        f'contract_fingerprint = "{contract_fingerprint}"',
        f'ack_source = "{args.ack_source}"',
        f'acknowledged_at = "{utc_now_iso()}"',
        f'note = "{args.note.replace(chr(34), chr(39))}"',
        'status = "acknowledged"',
        "",
    ]
    write_text(receipt_path, "\n".join(lines))
    print(receipt_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
