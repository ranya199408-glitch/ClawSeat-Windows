#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from liveness_gate import query_seat_liveness, restart_seat


class EscalationRequired(RuntimeError):
    """Raised when the hub role cannot be safely swallowed."""


def assign_owner(step_owner_role: str, seats_available: list[dict], project: str) -> str:
    """Enforce dispatch preference, restart, then SWALLOW fallback."""
    for seat in seats_available:
        if _field(seat, "role") == step_owner_role and _field(seat, "status", "alive") == "alive":
            session_name = _field(seat, "session_name")
            if session_name:
                return session_name

    if restart_seat(project, step_owner_role):
        restarted = _find_alive_role(step_owner_role, query_seat_liveness(project))
        if restarted:
            return restarted

    if step_owner_role == "memory":
        raise EscalationRequired("memory dead + restart failed -> AskUserQuestion")
    return f"planner [SWALLOW={step_owner_role}]"


def _find_alive_role(step_owner_role: str, seats_available: list[dict]) -> str | None:
    for seat in seats_available:
        if _field(seat, "role") == step_owner_role and _field(seat, "status", "alive") == "alive":
            session_name = _field(seat, "session_name")
            if session_name:
                return session_name
    return None


def _field(seat: Any, key: str, default: str = "") -> str:
    if isinstance(seat, dict):
        return str(seat.get(key, default) or default)
    return str(getattr(seat, key, default) or default)
