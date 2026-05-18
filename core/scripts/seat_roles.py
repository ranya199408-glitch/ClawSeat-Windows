from __future__ import annotations


def normalize_seat_role(role: str) -> str:
    """Normalize casing/whitespace for canonical seat role ids."""
    return str(role).strip().lower()
