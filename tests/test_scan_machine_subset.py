"""Tests for scan_environment.py machine/ subset enforcement (F2 reviewer finding).

Coverage:
  - Default full scan writes exactly the 5 MACHINE_DEFAULT_SCANNERS files
  - Default scan does NOT write legacy files (repos, gstack, clawseat) to machine/
  - machine/ file count ≤ 6 after default scan
  - machine/ files are within the known whitelist
  - --only repos still works (writes repos.json to machine/ when requested)
  - MACHINE_DEFAULT_SCANNERS constant contains exactly the expected 5 names
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
_SCAN_PY = _SCRIPTS / "scan_environment.py"
sys.path.insert(0, str(_SCRIPTS))


MACHINE_WHITELIST = frozenset({
    "credentials.json",
    "network.json",
    "openclaw.json",
    "github.json",
    "current_context.json",
    "system.json",
    "environment.json",
    "gstack.json",
    "clawseat.json",
})

LEGACY_FILES = frozenset({"repos.json"})


def run_scan(*extra_args: str, memory_dir: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCAN_PY), "--output", memory_dir, "--quiet"] + list(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ── MACHINE_DEFAULT_SCANNERS constant ─────────────────────────────────────────


def test_machine_default_scanners_has_5_entries():
    from scan_environment import MACHINE_DEFAULT_SCANNERS
    assert len(MACHINE_DEFAULT_SCANNERS) == 5


def test_machine_default_scanners_contains_core_five():
    from scan_environment import MACHINE_DEFAULT_SCANNERS
    assert set(MACHINE_DEFAULT_SCANNERS) == {
        "credentials", "network", "openclaw", "github", "current_context"
    }


# ── Default scan output ───────────────────────────────────────────────────────


def test_default_scan_produces_exactly_5_files(tmp_path):
    result = run_scan(memory_dir=str(tmp_path))
    assert result.returncode == 0, f"stderr: {result.stderr}"

    machine_dir = tmp_path / "machine"
    assert machine_dir.is_dir()
    machine_files = set(p.name for p in machine_dir.iterdir() if p.is_file())
    assert len(machine_files) == 5


def test_default_scan_file_count_le_6(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    machine_dir = tmp_path / "machine"
    count = sum(1 for p in machine_dir.iterdir() if p.is_file())
    assert count <= 6, f"Expected ≤6 files in machine/, got {count}: {list(machine_dir.iterdir())}"


def test_default_scan_files_within_whitelist(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    machine_dir = tmp_path / "machine"
    actual_files = set(p.name for p in machine_dir.iterdir() if p.is_file())
    unexpected = actual_files - MACHINE_WHITELIST
    assert not unexpected, f"Unexpected files in machine/: {unexpected}"


def test_default_scan_does_not_write_repos(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert not (tmp_path / "machine" / "repos.json").exists()


def test_default_scan_does_not_write_gstack(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert not (tmp_path / "machine" / "gstack.json").exists()


def test_default_scan_does_not_write_clawseat(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert not (tmp_path / "machine" / "clawseat.json").exists()


def test_default_scan_writes_current_context(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert (tmp_path / "machine" / "current_context.json").exists()


def test_default_scan_writes_credentials(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert (tmp_path / "machine" / "credentials.json").exists()


def test_default_scan_writes_network(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert (tmp_path / "machine" / "network.json").exists()


def test_default_scan_writes_github(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert (tmp_path / "machine" / "github.json").exists()


def test_default_scan_writes_openclaw(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert (tmp_path / "machine" / "openclaw.json").exists()


def test_index_is_at_root_not_machine(tmp_path):
    run_scan(memory_dir=str(tmp_path))
    assert (tmp_path / "index.json").exists()
    assert not (tmp_path / "machine" / "index.json").exists()


# ── Legacy scanners still accessible via --only ───────────────────────────────


def test_only_repos_writes_to_machine(tmp_path):
    result = run_scan("--only", "repos", memory_dir=str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "machine" / "repos.json").exists()


def test_only_system_writes_to_machine(tmp_path):
    result = run_scan("--only", "system", memory_dir=str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "machine" / "system.json").exists()


def test_only_combined_keeps_count_controlled(tmp_path):
    # Explicitly requesting 6 scanners gives 6 files
    result = run_scan(
        "--only", "credentials,network,openclaw,github,current_context,system",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    machine_files = list((tmp_path / "machine").iterdir())
    assert len(machine_files) == 6
