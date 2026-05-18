"""P1 tests for core/lib/profile_validator.py.

One test per §7 rule. Covers validate_profile_v2, validate_machine_config,
and write_validated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))

from machine_config import MachineConfig, MemoryService, OpenClawTenant  # noqa: E402
from profile_validator import (  # noqa: E402
    ProfileValidationError,
    ValidationResult,
    validate_machine_config,
    validate_profile_v2,
    write_validated,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _write_toml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _minimal_v2_profile(*, frontstage_agent: str = "yu", seats: list | None = None) -> dict:
    return {
        "version": 2,
        "profile_name": "install",
        "project_name": "install",
        "openclaw_frontstage_agent": frontstage_agent,
        "seats": seats if seats is not None else ["memory", "planner", "builder", "reviewer", "patrol", "designer"],
        "machine_services": ["memory"],
    }


def _make_machine_cfg(tmp_path: Path, tenant_names: list[str] | None = None) -> MachineConfig:
    tenants: dict[str, OpenClawTenant] = {}
    for name in (tenant_names or ["yu"]):
        ws = tmp_path / f"workspace-{name}"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "WORKSPACE_CONTRACT.toml").write_text(f'project = "install"\n')
        tenants[name] = OpenClawTenant(name=name, workspace=ws)
    return MachineConfig(
        version=1,
        memory=MemoryService(),
        tenants=tenants,
        source_path=tmp_path / "machine.toml",
    )


# ── Rule 1: version == 2 ──────────────────────────────────────────────


def test_v1_profile_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    raw = _minimal_v2_profile()
    raw["version"] = 1
    content = "\n".join(f'{k} = {repr(v)}' for k, v in raw.items() if not isinstance(v, (dict, list)))
    content += '\nseats = ["ancestor", "planner"]\n'
    _write_toml(path, content)
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("version" in e for e in result.errors)


def test_version_missing_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, 'profile_name = "test"\nseats = ["ancestor", "planner"]\n')
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("version" in e for e in result.errors)


# ── Rule 8: deprecated fields ─────────────────────────────────────────


def test_heartbeat_transport_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    raw = _minimal_v2_profile()
    _write_toml(path, (
        'version = 2\n'
        'heartbeat_transport = "tmux"\n'
        'seats = ["ancestor", "planner"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("heartbeat_transport" in e for e in result.errors)


def test_heartbeat_owner_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nheartbeat_owner = "koder"\n'
        'seats = ["ancestor", "planner"]\nopenclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("heartbeat_owner" in e for e in result.errors)


def test_heartbeat_seats_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nheartbeat_seats = ["planner"]\n'
        'seats = ["ancestor", "planner"]\nopenclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("heartbeat_seats" in e for e in result.errors)


def test_memory_primary_in_seats_allowed(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["memory", "planner"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert result.ok


def test_koder_in_seats_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "koder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("koder" in e for e in result.errors)


def test_builder_numbered_in_seats_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "builder-1"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("builder-1" in e for e in result.errors)


# ── Rules 2, 3: seats subset + superset ──────────────────────────────


def test_illegal_seat_name_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "wizard"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("wizard" in e for e in result.errors)


def test_missing_primary_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["planner", "builder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("primary" in e and "memory" in e and "ancestor" in e for e in result.errors)


def test_missing_planner_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "builder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("planner" in e for e in result.errors)


def test_seats_only_builder_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, 'version = 2\nseats = ["builder"]\nopenclaw_frontstage_agent = "yu"\n')
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("primary" in e or "planner" in e for e in result.errors)


# ── Rule 4: no duplicates ─────────────────────────────────────────────


def test_duplicate_seats_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "builder", "builder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("duplicate" in e for e in result.errors)


# ── Rule 5: openclaw_frontstage_agent cross-validation ───────────────


def test_unknown_frontstage_tenant_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner"]\n'
        'openclaw_frontstage_agent = "ghost"\n'
    ))
    machine_cfg = _make_machine_cfg(tmp_path)
    result = validate_profile_v2(path, machine_cfg=machine_cfg)
    assert not result.ok
    assert any("ghost" in e for e in result.errors)
    assert any("yu" in e for e in result.errors)  # shows known tenants


def test_missing_frontstage_agent_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, 'version = 2\nseats = ["ancestor", "planner"]\n')
    machine_cfg = _make_machine_cfg(tmp_path)
    result = validate_profile_v2(path, machine_cfg=machine_cfg)
    assert not result.ok
    assert any("openclaw_frontstage_agent" in e for e in result.errors)


# ── Rules 9, 10: parallel_instances ──────────────────────────────────


def test_parallel_instances_planner_gt1_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner"]\n'
        'openclaw_frontstage_agent = "yu"\n'
        '[seat_overrides.planner]\ntool = "claude"\nauth_mode = "oauth_token"\n'
        'provider = "anthropic"\nparallel_instances = 2\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("planner" in e and "parallel_instances" in e for e in result.errors)


def test_parallel_instances_builder_11_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "builder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
        '[seat_overrides.builder]\ntool = "claude"\nauth_mode = "oauth_token"\n'
        'provider = "anthropic"\nparallel_instances = 11\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("11" in e or "10" in e or "range" in e for e in result.errors)


def test_parallel_instances_ancestor_gt1_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner"]\n'
        'openclaw_frontstage_agent = "yu"\n'
        '[seat_overrides.ancestor]\ntool = "claude"\nauth_mode = "oauth_token"\n'
        'provider = "anthropic"\nparallel_instances = 2\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("ancestor" in e and "parallel_instances" in e for e in result.errors)


def test_parallel_instances_designer_gt1_rejected(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "designer"]\n'
        'openclaw_frontstage_agent = "yu"\n'
        '[seat_overrides.designer]\ntool = "gemini"\nauth_mode = "oauth"\n'
        'provider = "google"\nparallel_instances = 3\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("designer" in e and "parallel_instances" in e for e in result.errors)


def test_parallel_instances_builder_valid(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "builder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
        '[seat_overrides.builder]\ntool = "claude"\nauth_mode = "oauth_token"\n'
        'provider = "anthropic"\nparallel_instances = 3\n'
    ))
    machine_cfg = _make_machine_cfg(tmp_path)
    result = validate_profile_v2(path, machine_cfg=machine_cfg)
    assert result.ok or not any("parallel_instances" in e for e in result.errors)


# ── Rule 12: PROJECT_BINDING cross-validation ─────────────────────────


def test_binding_tenant_mismatch_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    # Write a PROJECT_BINDING.toml that disagrees with the profile.
    binding_dir = tmp_path / ".agents" / "tasks" / "install"
    binding_dir.mkdir(parents=True)
    (binding_dir / "PROJECT_BINDING.toml").write_text(
        'version = 1\nproject = "install"\nfeishu_group_id = "oc_abc"\n'
        'feishu_bot_account = "koder"\nrequire_mention = false\nbound_at = "2026"\n'
        'openclaw_frontstage_tenant = "different-tenant"\n'
    )
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nproject_name = "install"\n'
        'seats = ["ancestor", "planner"]\nopenclaw_frontstage_agent = "yu"\n'
    ))
    result = validate_profile_v2(path)
    assert not result.ok
    assert any("mismatch" in e or "different-tenant" in e for e in result.errors)


# ── Valid v2 profile ──────────────────────────────────────────────────


def test_valid_v2_profile_ok(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "builder", "reviewer", "patrol", "designer"]\n'
        'openclaw_frontstage_agent = "yu"\n'
        'profile_name = "install"\nproject_name = "install"\n'
    ))
    machine_cfg = _make_machine_cfg(tmp_path)
    result = validate_profile_v2(path, machine_cfg=machine_cfg)
    assert result.ok
    assert result.errors == []


def test_valid_v2_no_designer_gives_warning(tmp_path):
    path = tmp_path / "profile.toml"
    _write_toml(path, (
        'version = 2\nseats = ["ancestor", "planner", "builder"]\n'
        'openclaw_frontstage_agent = "yu"\n'
    ))
    machine_cfg = _make_machine_cfg(tmp_path)
    result = validate_profile_v2(path, machine_cfg=machine_cfg)
    # No errors about seats themselves (may still error on other rules if
    # machine not provided, but with machine it should pass).
    assert "designer" not in " ".join(result.errors)
    assert any("designer" in w for w in result.warnings)


# ── validate_machine_config ───────────────────────────────────────────


def test_machine_config_valid(tmp_path):
    path = tmp_path / "machine.toml"
    path.write_text((
        'version = 1\n[services.memory]\nrole = "memory-oracle"\n'
        'tool = "claude"\nauth_mode = "api"\nprovider = "minimax"\n'
    ))
    result = validate_machine_config(path)
    assert result.ok


def test_machine_config_wrong_version(tmp_path):
    path = tmp_path / "machine.toml"
    path.write_text((
        'version = 2\n[services.memory]\nrole = "memory-oracle"\n'
        'tool = "claude"\nauth_mode = "api"\nprovider = "minimax"\n'
    ))
    result = validate_machine_config(path)
    assert not result.ok
    assert any("version" in e for e in result.errors)


def test_machine_config_missing_memory(tmp_path):
    path = tmp_path / "machine.toml"
    path.write_text('version = 1\n')
    result = validate_machine_config(path)
    assert not result.ok
    assert any("memory" in e for e in result.errors)


def test_machine_config_bad_auth_mode(tmp_path):
    path = tmp_path / "machine.toml"
    path.write_text((
        'version = 1\n[services.memory]\nrole = "memory-oracle"\n'
        'tool = "claude"\nauth_mode = "oauth"\nprovider = "minimax"\n'
    ))
    result = validate_machine_config(path)
    assert not result.ok
    assert any("auth_mode" in e for e in result.errors)


def test_machine_config_bad_tenant_name(tmp_path):
    path = tmp_path / "machine.toml"
    path.write_text((
        'version = 1\n[services.memory]\nrole = "memory-oracle"\n'
        'tool = "claude"\nauth_mode = "api"\nprovider = "minimax"\n'
        '[openclaw_tenants."BAD-NAME"]\nworkspace = "/tmp/x"\n'
    ))
    result = validate_machine_config(path)
    assert not result.ok
    assert any("tenant name" in e or "BAD-NAME" in e for e in result.errors)


def test_machine_config_not_found(tmp_path):
    result = validate_machine_config(tmp_path / "missing.toml")
    assert not result.ok
    assert any("not found" in e for e in result.errors)


# ── write_validated ───────────────────────────────────────────────────


def test_write_validated_valid_profile(tmp_path):
    path = tmp_path / "out.toml"
    payload = {
        "version": 2,
        "seats": ["ancestor", "planner"],
        "openclaw_frontstage_agent": "yu",
    }
    written = write_validated(payload, path)
    assert written == path
    assert path.exists()
    content = path.read_text()
    assert "version = 2" in content


def test_write_validated_invalid_raises(tmp_path):
    path = tmp_path / "out.toml"
    payload = {
        "version": 2,
        "seats": ["planner"],  # missing ancestor
        "openclaw_frontstage_agent": "yu",
    }
    with pytest.raises(ProfileValidationError) as exc_info:
        write_validated(payload, path)
    assert "ancestor" in str(exc_info.value)
    assert not path.exists()


def test_write_validated_atomic(tmp_path):
    """tmp file should not exist after successful write."""
    path = tmp_path / "out.toml"
    payload = {
        "version": 2,
        "seats": ["ancestor", "planner"],
        "openclaw_frontstage_agent": "yu",
    }
    write_validated(payload, path)
    assert not path.with_suffix(".toml.tmp").exists()
