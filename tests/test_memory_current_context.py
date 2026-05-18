"""Tests for current_context.json generation in scan_environment.py.

Coverage:
  - scan_current_context() writes current_context.json into machine/
  - last_refresh_ts is a valid ISO-8601 string
  - current_project read from CLAWSEAT_PROJECT env var
  - current_project read from AGENTS_PROJECT env var when CLAWSEAT_PROJECT absent
  - current_project_dir read from CLAWSEAT_WORKSPACE_ROOT
  - current_project is None when no env var is set
  - Full scan writes machine/current_context.json
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
_SCAN_PY = _SCRIPTS / "scan_environment.py"
sys.path.insert(0, str(_SCRIPTS))


# ── Helper ────────────────────────────────────────────────────────────────────

_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)


def run_scan(*extra_args: str, env: dict | None = None, memory_dir: str = "") -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCAN_PY), "--quiet"]
    if memory_dir:
        cmd += ["--output", memory_dir]
    cmd += list(extra_args)
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=merged_env)


# ── Unit tests for scan_current_context() ────────────────────────────────────


def test_scan_current_context_returns_dict(monkeypatch):
    monkeypatch.delenv("CLAWSEAT_PROJECT", raising=False)
    monkeypatch.delenv("AGENTS_PROJECT", raising=False)
    monkeypatch.delenv("CLAWSEAT_WORKSPACE_ROOT", raising=False)

    from scan_environment import scan_current_context
    result = scan_current_context()
    assert isinstance(result, dict)


def test_last_refresh_ts_is_iso8601(monkeypatch):
    monkeypatch.delenv("CLAWSEAT_PROJECT", raising=False)
    monkeypatch.delenv("AGENTS_PROJECT", raising=False)
    monkeypatch.delenv("CLAWSEAT_WORKSPACE_ROOT", raising=False)

    from scan_environment import scan_current_context
    result = scan_current_context()
    ts = result.get("last_refresh_ts", "")
    assert _ISO8601_RE.match(ts), f"last_refresh_ts not ISO-8601: {ts!r}"


def test_scanned_at_is_iso8601(monkeypatch):
    monkeypatch.delenv("CLAWSEAT_PROJECT", raising=False)
    monkeypatch.delenv("AGENTS_PROJECT", raising=False)
    monkeypatch.delenv("CLAWSEAT_WORKSPACE_ROOT", raising=False)

    from scan_environment import scan_current_context
    result = scan_current_context()
    ts = result.get("scanned_at", "")
    assert _ISO8601_RE.match(ts), f"scanned_at not ISO-8601: {ts!r}"


def test_current_project_from_clawseat_project(monkeypatch):
    monkeypatch.setenv("CLAWSEAT_PROJECT", "my-project")
    monkeypatch.delenv("AGENTS_PROJECT", raising=False)

    from importlib import reload
    import scan_environment
    reload(scan_environment)

    result = scan_environment.scan_current_context()
    assert result["current_project"] == "my-project"


def test_current_project_from_agents_project_fallback(monkeypatch):
    monkeypatch.delenv("CLAWSEAT_PROJECT", raising=False)
    monkeypatch.setenv("AGENTS_PROJECT", "fallback-project")

    from importlib import reload
    import scan_environment
    reload(scan_environment)

    result = scan_environment.scan_current_context()
    assert result["current_project"] == "fallback-project"


def test_clawseat_project_takes_precedence(monkeypatch):
    monkeypatch.setenv("CLAWSEAT_PROJECT", "primary")
    monkeypatch.setenv("AGENTS_PROJECT", "secondary")

    from importlib import reload
    import scan_environment
    reload(scan_environment)

    result = scan_environment.scan_current_context()
    assert result["current_project"] == "primary"


def test_current_project_none_when_no_env(monkeypatch):
    monkeypatch.delenv("CLAWSEAT_PROJECT", raising=False)
    monkeypatch.delenv("AGENTS_PROJECT", raising=False)

    from importlib import reload
    import scan_environment
    reload(scan_environment)

    result = scan_environment.scan_current_context()
    assert result["current_project"] is None


def test_current_project_dir_from_workspace_root(monkeypatch):
    monkeypatch.setenv("CLAWSEAT_WORKSPACE_ROOT", "/tmp/my-workspace")
    monkeypatch.delenv("CLAWSEAT_PROJECT", raising=False)
    monkeypatch.delenv("AGENTS_PROJECT", raising=False)

    from importlib import reload
    import scan_environment
    reload(scan_environment)

    result = scan_environment.scan_current_context()
    assert result["current_project_dir"] == "/tmp/my-workspace"


def test_current_project_dir_none_when_no_env(monkeypatch):
    monkeypatch.delenv("CLAWSEAT_WORKSPACE_ROOT", raising=False)

    from importlib import reload
    import scan_environment
    reload(scan_environment)

    result = scan_environment.scan_current_context()
    assert result["current_project_dir"] is None


# ── Integration: scanner writes machine/current_context.json ─────────────────


def test_scan_current_context_only_creates_file(tmp_path):
    result = run_scan("--only", "current_context", memory_dir=str(tmp_path))
    assert result.returncode == 0, f"stderr: {result.stderr}"

    ctx_path = tmp_path / "machine" / "current_context.json"
    assert ctx_path.exists(), f"current_context.json not found at {ctx_path}"


def test_scan_current_context_json_is_valid(tmp_path):
    run_scan("--only", "current_context", memory_dir=str(tmp_path))
    ctx_path = tmp_path / "machine" / "current_context.json"
    data = json.loads(ctx_path.read_text())
    assert "last_refresh_ts" in data
    assert _ISO8601_RE.match(data["last_refresh_ts"])


def test_full_scan_writes_current_context_in_machine_dir(tmp_path):
    result = run_scan("--only", "current_context,network", memory_dir=str(tmp_path))
    assert result.returncode == 0
    assert (tmp_path / "machine" / "current_context.json").exists()
    assert (tmp_path / "machine" / "network.json").exists()


def test_scan_all_creates_machine_subdir(tmp_path):
    # Only run fast scanners to avoid network calls
    result = run_scan(
        "--only", "network,current_context",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    machine_dir = tmp_path / "machine"
    assert machine_dir.is_dir()
    assert (machine_dir / "current_context.json").exists()


def test_scan_with_project_env_stores_in_json(tmp_path):
    env = {"CLAWSEAT_PROJECT": "test-proj"}
    result = run_scan("--only", "current_context", memory_dir=str(tmp_path), env=env)
    assert result.returncode == 0
    data = json.loads((tmp_path / "machine" / "current_context.json").read_text())
    assert data["current_project"] == "test-proj"
