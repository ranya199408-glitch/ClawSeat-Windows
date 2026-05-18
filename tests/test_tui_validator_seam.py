"""P1 seam test: write_validated integration (§9 TUI-engine contract).

Tests:
- write a valid v2 payload via write_validated → succeeds, file on disk
- write an invalid payload (missing ancestor) → raises ProfileValidationError
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))

from profile_validator import ProfileValidationError, write_validated  # noqa: E402


def test_write_validated_valid_v2_succeeds(tmp_path):
    """A valid v2 profile passes write_validated and lands on disk."""
    path = tmp_path / "profile.toml"
    payload = {
        "version": 2,
        "profile_name": "test",
        "project_name": "test",
        "openclaw_frontstage_agent": "yu",
        "seats": ["ancestor", "planner", "builder", "reviewer", "patrol", "designer"],
        "machine_services": ["memory"],
    }
    written = write_validated(payload, path)
    assert written == path
    assert path.exists()
    content = path.read_text()
    assert "version = 2" in content
    assert "ancestor" in content


def test_write_validated_missing_ancestor_raises_profile_validation_error(tmp_path):
    """A payload with missing ancestor raises ProfileValidationError (not silently written)."""
    path = tmp_path / "profile.toml"
    payload = {
        "version": 2,
        "profile_name": "test",
        "project_name": "test",
        "openclaw_frontstage_agent": "yu",
        "seats": ["planner", "builder"],  # missing ancestor
    }
    with pytest.raises(ProfileValidationError) as exc_info:
        write_validated(payload, path)

    assert "ancestor" in str(exc_info.value)
    assert exc_info.value.errors  # errors list is populated
    assert not path.exists()  # nothing written


def test_write_validated_version_mismatch_raises(tmp_path):
    """v1 profile payload raises ProfileValidationError."""
    path = tmp_path / "profile.toml"
    payload = {
        "version": 1,
        "seats": ["ancestor", "planner"],
        "openclaw_frontstage_agent": "yu",
    }
    with pytest.raises(ProfileValidationError) as exc_info:
        write_validated(payload, path)
    assert any("version" in e for e in exc_info.value.errors)
