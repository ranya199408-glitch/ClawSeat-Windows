"""Regression: clawseat-engineering template loads correctly.

Verifies that the template introduced in FEAT-HARNESS-TEMPLATES is syntactically
valid TOML, has the expected seat count, and that each seat has the required fields
(id, role, tool, auth_mode).

clawseat-creative was deprecated 2026-05-02 (BV-2).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

_REPO = Path(__file__).resolve().parents[1]
_TEMPLATES = _REPO / "templates"


def _load(name: str) -> dict:
    path = _TEMPLATES / f"{name}.toml"
    assert path.exists(), f"template not found: {path}"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _validate_seats(data: dict) -> list[dict]:
    engineers = data.get("engineers", [])
    assert engineers, "template has no engineers"
    for eng in engineers:
        for field in ("id", "role", "tool", "auth_mode"):
            assert field in eng, f"seat {eng.get('id', '?')} missing field: {field}"
    return engineers


def test_clawseat_engineering_loads_with_five_seats() -> None:
    data = _load("clawseat-engineering")
    seats = _validate_seats(data)
    assert len(seats) == 5, f"expected 5 seats, got {len(seats)}: {[s['id'] for s in seats]}"
    seat_ids = [s["id"] for s in seats]
    assert "memory" in seat_ids
    assert "planner" in seat_ids
    assert "builder" in seat_ids
    assert "reviewer" in seat_ids
    assert "patrol" in seat_ids


def test_clawseat_engineering_builder_is_codex_oauth() -> None:
    data = _load("clawseat-engineering")
    builder = next(e for e in data["engineers"] if e["id"] == "builder")
    assert builder["tool"] == "codex"
    assert builder["auth_mode"] == "oauth"
    assert builder["provider"] == "openai"


# clawseat-creative tests removed — template deprecated 2026-05-02 (BV-2)
