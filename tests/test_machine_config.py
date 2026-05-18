"""P1 tests for core/lib/machine_config.py.

Covers: round-trip, auto-discovery, validate_tenant, defaults, list tenants.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))

from machine_config import (  # noqa: E402
    MachineConfig,
    MachineConfigError,
    MemoryService,
    OpenClawTenant,
    default_path,
    list_openclaw_tenants,
    load_machine,
    validate_tenant,
    write_machine,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_config(tmp_path: Path, *, tenants: dict | None = None) -> MachineConfig:
    t: dict[str, OpenClawTenant] = {}
    if tenants:
        for name, ws in tenants.items():
            t[name] = OpenClawTenant(name=name, workspace=ws, description="test tenant")
    return MachineConfig(
        version=1,
        memory=MemoryService(),
        tenants=t,
        source_path=tmp_path / "machine.toml",
    )


# ── default_path respects CLAWSEAT_REAL_HOME ─────────────────────────


def test_default_path_uses_clawseat_real_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    p = default_path()
    assert str(p).startswith(str(tmp_path))
    assert p.name == "machine.toml"
    assert ".clawseat" in str(p)


# ── Round-trip write → load ───────────────────────────────────────────


def test_round_trip_no_tenants(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = _make_config(tmp_path)
    cfg.source_path = path
    written = write_machine(cfg, path)
    assert written == path
    loaded = load_machine(path)
    assert loaded.version == 1
    assert loaded.memory.role == "memory-oracle"
    assert loaded.memory.tool == "claude"
    assert loaded.memory.provider == "minimax"
    assert loaded.memory.model == "MiniMax-M2.7-highspeed"
    assert loaded.tenants == {}


def test_round_trip_with_tenants(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    # Set up fake tenant workspaces.
    ws_yu = tmp_path / ".openclaw" / "workspace-yu"
    ws_yu.mkdir(parents=True)
    (ws_yu / "WORKSPACE_CONTRACT.toml").write_text('project = "install"\n')

    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = _make_config(tmp_path, tenants={"yu": ws_yu})
    cfg.source_path = path
    write_machine(cfg, path)
    loaded = load_machine(path)
    assert "yu" in loaded.tenants
    assert loaded.tenants["yu"].name == "yu"
    assert loaded.tenants["yu"].workspace == ws_yu


def test_round_trip_preserves_launch_args(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = _make_config(tmp_path)
    cfg.source_path = path
    cfg.memory.launch_args = ["--dangerously-skip-permissions"]
    write_machine(cfg, path)
    loaded = load_machine(path)
    assert loaded.memory.launch_args == ["--dangerously-skip-permissions"]


def test_round_trip_monitor_false(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = _make_config(tmp_path)
    cfg.source_path = path
    cfg.memory.monitor = False
    write_machine(cfg, path)
    loaded = load_machine(path)
    assert loaded.memory.monitor is False


# ── Auto-discovery ────────────────────────────────────────────────────


def test_auto_discovery_no_openclaw(tmp_path, monkeypatch):
    """No ~/.openclaw dir → empty tenants, file created with defaults."""
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    path = tmp_path / ".clawseat" / "machine.toml"
    assert not path.exists()
    cfg = load_machine(path)
    assert path.exists()
    assert cfg.tenants == {}
    assert cfg.memory.provider == "minimax"


def test_auto_discovery_two_workspaces(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    for name in ("yu", "mor"):
        ws = tmp_path / ".openclaw" / f"workspace-{name}"
        ws.mkdir(parents=True)
        (ws / "WORKSPACE_CONTRACT.toml").write_text(f'project = "{name}-project"\n')
    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = load_machine(path)
    assert "yu" in cfg.tenants
    assert "mor" in cfg.tenants


def test_auto_discovery_ignores_non_workspace_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    oc = tmp_path / ".openclaw"
    oc.mkdir(parents=True)
    (oc / "random-dir").mkdir()
    (oc / "workspace-valid").mkdir()
    (oc / "workspace-valid" / "WORKSPACE_CONTRACT.toml").write_text("")
    # "workspace-INVALID" — uppercase not matching [a-z]
    (oc / "workspace-INVALID").mkdir()
    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = load_machine(path)
    assert "valid" in cfg.tenants
    assert "INVALID" not in cfg.tenants
    assert "random-dir" not in cfg.tenants


# ── validate_tenant ───────────────────────────────────────────────────


def test_validate_tenant_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    ws = tmp_path / ".openclaw" / "workspace-yu"
    ws.mkdir(parents=True)
    (ws / "WORKSPACE_CONTRACT.toml").write_text('project = "install"\n')
    cfg = _make_config(tmp_path, tenants={"yu": ws})
    ok, err = validate_tenant(cfg, "yu")
    assert ok is True
    assert err == ""


def test_validate_tenant_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    cfg = _make_config(tmp_path)
    ok, err = validate_tenant(cfg, "ghost")
    assert ok is False
    assert "ghost" in err


def test_validate_tenant_workspace_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    ws = tmp_path / ".openclaw" / "workspace-yu"
    cfg = _make_config(tmp_path, tenants={"yu": ws})
    ok, err = validate_tenant(cfg, "yu")
    assert ok is False
    assert "does not exist" in err


def test_validate_tenant_no_workspace_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    ws = tmp_path / ".openclaw" / "workspace-yu"
    ws.mkdir(parents=True)
    # No WORKSPACE_CONTRACT.toml
    cfg = _make_config(tmp_path, tenants={"yu": ws})
    ok, err = validate_tenant(cfg, "yu")
    assert ok is False
    assert "WORKSPACE_CONTRACT.toml" in err


# ── list_openclaw_tenants ─────────────────────────────────────────────


def test_list_tenants_sorted(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    ws_a = tmp_path / "workspace-a"
    ws_b = tmp_path / "workspace-b"
    ws_a.mkdir(); ws_b.mkdir()
    cfg = _make_config(tmp_path, tenants={"b": ws_b, "a": ws_a})
    result = list_openclaw_tenants(cfg)
    assert [t.name for t in result] == ["a", "b"]


def test_list_tenants_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    cfg = _make_config(tmp_path)
    assert list_openclaw_tenants(cfg) == []


# ── write_machine atomic ──────────────────────────────────────────────


def test_write_machine_creates_parent_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    path = tmp_path / "deep" / "nested" / "machine.toml"
    cfg = _make_config(tmp_path)
    cfg.source_path = path
    write_machine(cfg, path)
    assert path.exists()
    assert not path.with_suffix(".toml.tmp").exists()


def test_load_machine_parse_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    path = tmp_path / "machine.toml"
    path.write_text("{ not valid toml !!!!")
    with pytest.raises(MachineConfigError, match="cannot parse"):
        load_machine(path)
