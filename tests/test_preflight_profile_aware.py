"""Tests for T5-A: profile-aware skill validation in preflight / skill_registry.

Gate: required skills with roles not in active_roles are downgraded to optional,
so starter.toml profiles (roles={frontstage-supervisor}) are not HARD_BLOCKED
by builder/reviewer/patrol/designer skills they don't need.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

from core.skill_registry import SkillEntry, SkillCheckResult, validate_all


# ── helpers ───────────────────────────────────────────────────────────────────

def _missing_entry(name: str, roles: list[str], required: bool = True) -> SkillEntry:
    """Construct a SkillEntry that will always be missing (non-existent path)."""
    return SkillEntry(
        name=name,
        source="gstack",
        path="/nonexistent/__never__/SKILL.md",
        required=required,
        roles=roles,
    )


# ── validate_all with active_roles=None (existing behaviour) ──────────────────


def test_validate_all_no_filter_required_missing_is_blocked():
    """Without active_roles, missing required skill is in required_missing."""
    entries = [_missing_entry("gstack-investigate", roles=["builder"])]
    result = validate_all(entries)
    assert result.required_missing, "expected gstack-investigate in required_missing"
    assert result.required_missing[0].name == "gstack-investigate"


def test_validate_all_no_filter_preserves_existing_behaviour():
    """active_roles=None is the same as calling validate_all() with no extra arg."""
    entries = [_missing_entry("gstack-review", roles=["reviewer"])]
    r1 = validate_all(entries)
    r2 = validate_all(entries, active_roles=None)
    assert len(r1.required_missing) == len(r2.required_missing) == 1


# ── validate_all with active_roles filtering ──────────────────────────────────


def test_validate_all_active_roles_filters_role_specific_required():
    """builder skill downgraded to optional when active_roles={frontstage-supervisor}."""
    entries = [_missing_entry("gstack-investigate", roles=["builder"])]
    result = validate_all(entries, active_roles={"frontstage-supervisor"})
    assert not result.required_missing, "should not be hard-required for starter profile"
    assert result.optional_missing, "should appear as optional_missing instead"
    assert result.optional_missing[0].name == "gstack-investigate"


def test_validate_all_active_roles_keeps_universal_required():
    """Skill with roles=[] (universal) stays required regardless of active_roles."""
    entries = [_missing_entry("gstack-harness", roles=[], required=True)]
    result = validate_all(entries, active_roles={"frontstage-supervisor"})
    assert result.required_missing, "universal skill must still be required_missing"
    assert result.required_missing[0].name == "gstack-harness"


def test_validate_all_active_roles_keeps_matching_required():
    """Skill with roles=[builder] stays required when active_roles includes builder."""
    entries = [_missing_entry("gstack-investigate", roles=["builder"])]
    result = validate_all(entries, active_roles={"builder", "reviewer"})
    assert result.required_missing, "builder skill must still be required when builder in active_roles"


def test_validate_all_active_roles_empty_set_filters_all_role_specific():
    """active_roles={} (no roles at all) downgrade all role-specific required skills."""
    entries = [
        _missing_entry("gstack-investigate", roles=["builder"]),
        _missing_entry("gstack-review", roles=["reviewer"]),
        _missing_entry("gstack-harness", roles=[]),  # universal — stays required
    ]
    result = validate_all(entries, active_roles=set())
    required_names = {i.name for i in result.required_missing}
    assert "gstack-investigate" not in required_names
    assert "gstack-review" not in required_names
    assert "gstack-harness" in required_names


# ── _load_active_roles helper ─────────────────────────────────────────────────


def test_load_active_roles_returns_none_for_missing_profile(tmp_path, monkeypatch):
    """_load_active_roles returns None when no profile file exists."""
    from core.preflight import _load_active_roles
    monkeypatch.setattr("core.preflight._dynamic_profile_path", lambda p: tmp_path / "nonexistent.toml")
    result = _load_active_roles("no-such-project")
    assert result is None


def test_load_active_roles_returns_roles_from_profile(tmp_path, monkeypatch):
    """_load_active_roles reads seat_roles values from a real profile TOML."""
    import tomllib
    profile = tmp_path / "starter-profile-dynamic.toml"
    profile.write_text(
        '[seat_roles]\nkoder = "frontstage-supervisor"\n'
    )
    monkeypatch.setattr("core.preflight._dynamic_profile_path", lambda p: profile)
    from core.preflight import _load_active_roles
    roles = _load_active_roles("starter")
    assert roles == {"frontstage-supervisor"}
