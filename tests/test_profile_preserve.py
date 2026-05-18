"""C14 tests: render_profile_preserving_operator_edits helper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))

from agent_admin_workspace import (  # noqa: E402
    PRESERVE_FIELDS,
    _serialize_profile_toml,
    _toml_val,
    render_profile_preserving_operator_edits,
)

try:
    import tomllib  # type: ignore[attr-defined]
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(_serialize_profile_toml(data), encoding="utf-8")


def _read_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _base_fresh() -> dict[str, Any]:
    return {
        "version": 1,
        "profile_name": "test-profile",
        "heartbeat_transport": "tmux",
        "heartbeat_owner": "koder",
        "seats": ["memory", "koder", "planner"],
        "heartbeat_seats": ["koder"],
        "active_loop_owner": "planner",
        "default_notify_target": "planner",
        "seat_roles": {
            "koder": "frontstage-supervisor",
            "planner": "planner-dispatcher",
        },
        "dynamic_roster": {
            "enabled": True,
            "materialized_seats": ["koder", "planner"],
            "runtime_seats": ["koder", "planner"],
            "bootstrap_seats": ["koder"],
            "default_start_seats": ["planner"],
        },
        "patrol": {
            "enabled": False,
        },
    }


# ---------------------------------------------------------------------------
# _toml_val tests
# ---------------------------------------------------------------------------


def test_toml_val_bool_true():
    assert _toml_val(True) == "true"


def test_toml_val_bool_false():
    assert _toml_val(False) == "false"


def test_toml_val_int():
    assert _toml_val(42) == "42"


def test_toml_val_str():
    assert _toml_val("hello") == '"hello"'


def test_toml_val_str_escape():
    assert _toml_val('say "hi"') == '"say \\"hi\\""'


def test_toml_val_list():
    assert _toml_val(["a", "b"]) == '["a", "b"]'


def test_toml_val_unsupported_raises():
    with pytest.raises(ValueError):
        _toml_val({"x": 1})  # type: ignore


# ---------------------------------------------------------------------------
# _serialize_profile_toml round-trip
# ---------------------------------------------------------------------------


def test_serialize_roundtrip_scalars():
    data = {"version": 1, "name": "test", "flag": True}
    text = _serialize_profile_toml(data)
    parsed = tomllib.loads(text)
    assert parsed == data


def test_serialize_roundtrip_list():
    data = {"seats": ["a", "b", "c"]}
    text = _serialize_profile_toml(data)
    parsed = tomllib.loads(text)
    assert parsed["seats"] == ["a", "b", "c"]


def test_serialize_roundtrip_nested_table():
    data = {"seat_roles": {"koder": "frontstage", "planner": "dispatcher"}}
    text = _serialize_profile_toml(data)
    parsed = tomllib.loads(text)
    assert parsed["seat_roles"] == {"koder": "frontstage", "planner": "dispatcher"}


def test_serialize_roundtrip_doubly_nested():
    data = {"seat_overrides": {"planner": {"tool": "claude", "auth_mode": "oauth"}}}
    text = _serialize_profile_toml(data)
    parsed = tomllib.loads(text)
    assert parsed["seat_overrides"]["planner"]["tool"] == "claude"
    assert parsed["seat_overrides"]["planner"]["auth_mode"] == "oauth"


def test_serialize_full_profile_roundtrip():
    data = _base_fresh()
    text = _serialize_profile_toml(data)
    parsed = tomllib.loads(text)
    assert parsed["seats"] == data["seats"]
    assert parsed["seat_roles"] == data["seat_roles"]
    assert parsed["dynamic_roster"]["default_start_seats"] == data["dynamic_roster"]["default_start_seats"]


# ---------------------------------------------------------------------------
# 1. Happy path preservation
# ---------------------------------------------------------------------------


def test_preserve_heartbeat_transport_openclaw(tmp_path):
    """existing has heartbeat_transport = 'openclaw'; fresh says 'tmux'. Result: 'openclaw' kept, warning emitted."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["heartbeat_transport"] = "openclaw"
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # has "tmux"
    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["heartbeat_transport"] == "openclaw"


def test_preserve_heartbeat_transport_emits_warning(tmp_path, capsys):
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["heartbeat_transport"] = "openclaw"
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # has "tmux"
    render_profile_preserving_operator_edits(existing_path, fresh)

    err = capsys.readouterr().err
    assert "heartbeat_transport" in err
    assert "openclaw" in err
    assert "tmux" in err


# ---------------------------------------------------------------------------
# 2. New field added by fresh payload
# ---------------------------------------------------------------------------


def test_new_field_in_fresh_added_to_merged(tmp_path):
    """existing has heartbeat_transport; fresh adds new_field. Result: both present."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()
    fresh["new_field"] = "added-in-v2"

    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert "heartbeat_transport" in result
    assert result["new_field"] == "added-in-v2"


# ---------------------------------------------------------------------------
# 3. Missing preserved field filled from fresh
# ---------------------------------------------------------------------------


def test_missing_preserved_field_filled_from_fresh(tmp_path):
    """existing missing heartbeat_transport; fresh has 'tmux'. Result: 'tmux' written."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    del existing_data["heartbeat_transport"]
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # has "tmux"
    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["heartbeat_transport"] == "tmux"


def test_missing_preserved_field_no_warning(tmp_path, capsys):
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    del existing_data["heartbeat_transport"]
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()
    render_profile_preserving_operator_edits(existing_path, fresh)

    err = capsys.readouterr().err
    # No warning when fresh just fills in what's missing
    assert "heartbeat_transport" not in err


# ---------------------------------------------------------------------------
# 4. Nested table preservation (seat_overrides)
# ---------------------------------------------------------------------------


def test_nested_seat_overrides_preserved(tmp_path):
    """existing has [seat_overrides.planner] with tool='claude'; fresh doesn't mention it. Result: preserved."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["seat_overrides"] = {
        "planner": {"tool": "claude", "auth_mode": "oauth"},
        "builder-1": {"tool": "codex", "auth_mode": "api"},
    }
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # no seat_overrides key
    assert "seat_overrides" not in fresh

    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["seat_overrides"]["planner"]["tool"] == "claude"
    assert result["seat_overrides"]["builder-1"]["tool"] == "codex"


def test_nested_seat_roles_preserved(tmp_path):
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["seat_roles"]["builder-1"] = "builder"
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()
    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["seat_roles"]["builder-1"] == "builder"


# ---------------------------------------------------------------------------
# 5. List field preservation (seats shrink)
# ---------------------------------------------------------------------------


def test_seats_list_preserved_when_fresh_shorter(tmp_path, capsys):
    """existing has 7-seat list; fresh has 5. Result: 7-seat list preserved, warning logged."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["seats"] = ["memory", "koder", "planner", "builder-1", "reviewer-1", "qa-1", "builder-2"]
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # seats = ["memory", "koder", "planner"]

    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert len(result["seats"]) == 7
    assert "builder-2" in result["seats"]
    err = capsys.readouterr().err
    assert "seats" in err


# ---------------------------------------------------------------------------
# 6. Explicit operator empty list
# ---------------------------------------------------------------------------


def test_explicit_empty_seats_preserved(tmp_path, capsys):
    """existing has seats = []; fresh has [a, b, c]. Result: [] preserved, warning logged."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["seats"] = []
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # seats = ["memory", "koder", "planner"]

    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["seats"] == []
    err = capsys.readouterr().err
    assert "seats" in err


# ---------------------------------------------------------------------------
# 7. Extras preservation
# ---------------------------------------------------------------------------


def test_extra_field_preserved(tmp_path):
    """existing has custom_future_field = 'x'; fresh doesn't. Result: preserved."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["custom_future_field"] = "x"
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()
    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["custom_future_field"] == "x"


def test_extra_table_preserved(tmp_path):
    """existing has [observability] table; fresh doesn't. Result: preserved."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["observability"] = {"enabled": True, "backend": "otlp"}
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()
    result = render_profile_preserving_operator_edits(existing_path, fresh)

    assert result["observability"]["enabled"] is True
    assert result["observability"]["backend"] == "otlp"


# ---------------------------------------------------------------------------
# 8. Non-existent target (fresh install)
# ---------------------------------------------------------------------------


def test_fresh_install_no_existing(tmp_path):
    """target_path does not exist — result is just fresh_payload."""
    target = tmp_path / "nonexistent.toml"
    fresh = _base_fresh()

    result = render_profile_preserving_operator_edits(target, fresh)

    assert result == fresh


def test_fresh_install_no_warning(tmp_path, capsys):
    target = tmp_path / "nonexistent.toml"
    render_profile_preserving_operator_edits(target, _base_fresh())
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# 9. Install flow regression (bootstrap simulation)
# ---------------------------------------------------------------------------


def test_bootstrap_preserves_openclaw_heartbeat(tmp_path):
    """Simulate a bootstrap run on a hand-edited profile — heartbeat_transport stays 'openclaw'."""
    profile_path = tmp_path / "install-profile-dynamic.toml"

    # Operator had previously set up the profile with openclaw transport
    existing = _base_fresh()
    existing["heartbeat_transport"] = "openclaw"
    existing["seats"] = ["memory", "koder", "planner", "builder-1", "reviewer-1", "qa-1", "builder-2"]
    _write_toml(profile_path, existing)

    # Fresh template (simulating what cs_init would load from install-with-memory.toml)
    fresh_template = _base_fresh()  # has heartbeat_transport = "tmux"
    assert fresh_template["heartbeat_transport"] == "tmux"

    # Run the preservation merge
    merged = render_profile_preserving_operator_edits(profile_path, fresh_template)
    profile_path.write_text(_serialize_profile_toml(merged), encoding="utf-8")

    # Re-parse and verify
    result = _read_toml(profile_path)
    assert result["heartbeat_transport"] == "openclaw"
    assert len(result["seats"]) == 7


def test_bootstrap_no_existing_uses_fresh(tmp_path):
    """No existing profile → bootstrap writes the full fresh template cleanly."""
    profile_path = tmp_path / "install-profile-dynamic.toml"

    fresh = _base_fresh()
    merged = render_profile_preserving_operator_edits(profile_path, fresh)
    profile_path.write_text(_serialize_profile_toml(merged), encoding="utf-8")

    result = _read_toml(profile_path)
    assert result["heartbeat_transport"] == "tmux"
    assert result["seats"] == ["memory", "koder", "planner"]


# ---------------------------------------------------------------------------
# 10. PRESERVE_FIELDS constant sanity
# ---------------------------------------------------------------------------


def test_preserve_fields_contains_critical_keys():
    assert "heartbeat_transport" in PRESERVE_FIELDS
    assert "seats" in PRESERVE_FIELDS
    assert "seat_overrides" in PRESERVE_FIELDS
    assert "seat_roles" in PRESERVE_FIELDS
    assert "dynamic_roster" in PRESERVE_FIELDS


# ---------------------------------------------------------------------------
# 11. No divergence warning when values match
# ---------------------------------------------------------------------------


def test_no_warning_when_values_match(tmp_path, capsys):
    """If existing and fresh agree on a preserved field, no warning emitted."""
    existing_path = tmp_path / "profile.toml"
    existing_data = _base_fresh()
    existing_data["heartbeat_transport"] = "tmux"  # same as fresh
    _write_toml(existing_path, existing_data)

    fresh = _base_fresh()  # heartbeat_transport = "tmux"
    render_profile_preserving_operator_edits(existing_path, fresh)

    err = capsys.readouterr().err
    assert "heartbeat_transport" not in err
