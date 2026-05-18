"""Heartbeat contract verification — extracted from _common.py."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from _utils import load_toml


def heartbeat_manifest_fingerprint(manifest: dict[str, Any]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def heartbeat_receipt_is_verified(
    *,
    receipt: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    seat: str,
    project: str,
) -> bool:
    if not receipt or not manifest:
        return False
    if str(receipt.get("status", "")).strip() != "verified":
        return False
    if str(receipt.get("seat_id", "")).strip() != seat:
        return False
    if str(receipt.get("project", "")).strip() != project:
        return False
    return str(receipt.get("manifest_fingerprint", "")).strip() == heartbeat_manifest_fingerprint(manifest)


def heartbeat_state(
    profile: object,
    seat: str,
) -> dict[str, Any]:
    from _common import heartbeat_manifest_path  # avoid circular — stays in _common

    manifest_path = heartbeat_manifest_path(profile, seat)  # type: ignore[arg-type]
    receipt_path = profile.heartbeat_receipt_for(seat)  # type: ignore[attr-defined]
    manifest = load_toml(manifest_path)
    receipt = load_toml(receipt_path)
    verified = heartbeat_receipt_is_verified(
        receipt=receipt,
        manifest=manifest,
        seat=seat,
        project=profile.project_name,  # type: ignore[attr-defined]
    )
    if verified:
        state = "verified"
    elif receipt:
        state = "unverified"
    else:
        state = "missing"
    return {
        "owner": seat,
        "configured": verified,
        "state": state,
        "manifest_path": str(manifest_path),
        "receipt_path": str(receipt_path),
        "manifest": manifest or {},
        "receipt": receipt or {},
    }
