from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / "core" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.lib.machine_config import MachineConfig, MemoryService, OpenClawTenant, load_machine, write_machine
from core.scripts.bootstrap_machine_tenants import bootstrap_machine_tenants


def _write_scan(memory_root: Path, agents: list[dict[str, str]]) -> None:
    machine_dir = memory_root / "machine"
    machine_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "scanned_at": "2026-04-22T00:00:00+00:00",
        "home": str(memory_root / "openclaw-home"),
        "exists": True,
        "agents": agents,
    }
    (machine_dir / "openclaw.json").write_text(json.dumps(payload), encoding="utf-8")


def _make_workspace(root: Path, name: str) -> Path:
    workspace = root / f"workspace-{name}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _seed_machine(tmp_path: Path, tenants: dict[str, OpenClawTenant] | None = None) -> Path:
    path = tmp_path / ".clawseat" / "machine.toml"
    cfg = MachineConfig(
        version=1,
        memory=MemoryService(),
        tenants=tenants or {},
        source_path=path,
    )
    write_machine(cfg, path)
    return path


def test_bootstrap_machine_tenants_adds_new_tenants(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    memory_root = tmp_path / "memory"
    ws_root = tmp_path / "workspaces"
    alpha = _make_workspace(ws_root, "alpha")
    beta = _make_workspace(ws_root, "beta")
    gamma = _make_workspace(ws_root, "gamma")
    _write_scan(
        memory_root,
        [
            {"name": "alpha", "workspace": str(alpha)},
            {"name": "beta", "workspace": str(beta)},
            {"name": "gamma", "workspace": str(gamma)},
        ],
    )

    rc = bootstrap_machine_tenants(memory_root)

    assert rc == 0
    cfg = load_machine(tmp_path / ".clawseat" / "machine.toml")
    assert sorted(cfg.tenants.keys()) == ["alpha", "beta", "gamma"]
    assert cfg.tenants["alpha"].description == "auto-registered by scan"
    assert cfg.tenants["beta"].workspace == beta
    assert cfg.tenants["gamma"].workspace == gamma


def test_bootstrap_machine_tenants_does_not_overwrite_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    memory_root = tmp_path / "memory"
    existing = _make_workspace(tmp_path / "existing", "alpha")
    replacement = _make_workspace(tmp_path / "replacement", "alpha")
    beta = _make_workspace(tmp_path / "replacement", "beta")
    _seed_machine(
        tmp_path,
        tenants={
            "alpha": OpenClawTenant(
                name="alpha",
                workspace=existing,
                description="manual tenant",
            ),
        },
    )
    _write_scan(
        memory_root,
        [
            {"name": "alpha", "workspace": str(replacement)},
            {"name": "beta", "workspace": str(beta)},
        ],
    )

    rc = bootstrap_machine_tenants(memory_root)

    assert rc == 0
    cfg = load_machine(tmp_path / ".clawseat" / "machine.toml")
    assert sorted(cfg.tenants.keys()) == ["alpha", "beta"]
    assert cfg.tenants["alpha"].workspace == existing
    assert cfg.tenants["alpha"].description == "manual tenant"
    assert cfg.tenants["beta"].workspace == beta


def test_bootstrap_machine_tenants_skips_missing_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    memory_root = tmp_path / "memory"
    present = _make_workspace(tmp_path / "workspaces", "present")
    missing = tmp_path / "workspaces" / "workspace-missing"
    _write_scan(
        memory_root,
        [
            {"name": "present", "workspace": str(present)},
            {"name": "missing", "workspace": str(missing)},
        ],
    )

    rc = bootstrap_machine_tenants(memory_root)

    assert rc == 0
    cfg = load_machine(tmp_path / ".clawseat" / "machine.toml")
    assert sorted(cfg.tenants.keys()) == ["present"]
    assert "missing" not in cfg.tenants


def test_load_machine_auto_discovery_uses_openclaw_home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    openclaw_home = tmp_path / "custom-openclaw"
    workspace = _make_workspace(openclaw_home, "envtenant")
    (workspace / "WORKSPACE_CONTRACT.toml").write_text('project = "install"\n', encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_HOME", str(openclaw_home))

    cfg = load_machine(tmp_path / ".clawseat" / "machine.toml")

    assert "envtenant" in cfg.tenants
    assert cfg.tenants["envtenant"].workspace == workspace
