"""
Smoke tests for scan_project.py using real repositories.

These smoke tests enforce SPEC §5.3.1/§5.3.2 real-repo hard gate. The hard
gate fires for any developer running on a box where the canonical repos
(`this ClawSeat checkout`, `/tmp/fake-home`) are installed —
running the suite there without the repos present is a bug in setup.

CI runners don't have those user-scoped paths and never will (they live
in the maintainer's home directory). Two narrow skip triggers are
therefore allowed, and only those:

- ``CI=true`` (GitHub Actions, GitLab, most providers set this)
- ``CLAWSEAT_SKIP_REAL_REPO_SMOKE=1`` (explicit opt-out for containers /
  non-canonical dev boxes)

Neither is automatic on the maintainer's workstation, so the hard gate
still catches "I deleted the repo by mistake" drift in local runs. See
SPEC §5.3.4 for the corresponding CI-escape-hatch clause.

SPEC deviations from §5.3 text (calibrated 2026-04-18):
  - ClawSeat has_ci=True (SPEC assumed False); has .github/workflows/ci.yml
  - cartooner python_version=None (SPEC assumed "3.11"); no .python-version / pyproject.toml
  - cartooner vitest=False (SPEC assumed True); vitest config not found
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "core/skills/memory-oracle/scripts"
SCAN_SCRIPT = SCRIPTS_DIR / "scan_project.py"
QUERY_SCRIPT = SCRIPTS_DIR / "query_memory.py"

CLAWSEAT_REPO = Path(__file__).resolve().parents[1]
CARTOONER_REPO = Path("/tmp/fake-home")


def _ci_skip_allowed() -> bool:
    """True when the running environment is a CI runner or explicitly
    opts out of the real-repo hard gate. These are the only scenarios
    where `pytest.skip` is preferred over `pytest.fail` — a missing repo
    on the maintainer's own box still fails loudly."""
    return (
        os.environ.get("CI", "").lower() in {"true", "1"}
        or os.environ.get("CLAWSEAT_SKIP_REAL_REPO_SMOKE", "") == "1"
    )


def _require_repo(repo: Path, label: str) -> None:
    if repo.exists():
        return
    message = (
        f"real repo missing at {repo} (label={label}); "
        "SPEC §5.3.1/§5.3.2 mandates this as hard gate for local runs."
    )
    if _ci_skip_allowed():
        pytest.skip(message + " Skipped because CI or CLAWSEAT_SKIP_REAL_REPO_SMOKE is set.")
    pytest.fail(message + " Cannot silently skip on a maintainer workstation.")


def _require_clawseat() -> None:
    _require_repo(CLAWSEAT_REPO, "clawseat")


def _require_cartooner() -> None:
    _require_repo(CARTOONER_REPO, "cartooner")


def _run_scan(
    project: str,
    repo: Path,
    depth: str,
    tmp_path: Path,
    *,
    commit: bool = False,
    force_commit: bool = False,
) -> dict:
    """Run scan_project.py and return parsed JSON output (dry-run) or {} (commit)."""
    cmd = [
        sys.executable,
        str(SCAN_SCRIPT),
        "--project", project,
        "--repo", str(repo),
        "--depth", depth,
        "--memory-dir", str(tmp_path),
        "--quiet",
    ]
    if force_commit:
        cmd.append("--force-commit")
    elif commit:
        cmd.append("--commit")

    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"scan failed: {result.stderr}"

    if not commit and not force_commit:
        return json.loads(result.stdout)
    return {}


def _run_query(project: str, kind: str, tmp_path: Path) -> list:
    """Run query_memory.py and return parsed JSON list."""
    cmd = [
        sys.executable,
        str(QUERY_SCRIPT),
        "--project", project,
        "--kind", kind,
        "--memory-dir", str(tmp_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"query failed: {result.stderr}"
    return json.loads(result.stdout)


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_clawseat_shallow_scan(tmp_path):
    """ClawSeat shallow scan writes dev_env.json with correct anchors."""
    _require_clawseat()
    _run_scan("clawseat", CLAWSEAT_REPO, "shallow", tmp_path, commit=True)
    dev_env_file = tmp_path / "projects/clawseat/dev_env.json"
    assert dev_env_file.exists()
    rec = json.loads(dev_env_file.read_text())
    data = rec["data"]
    assert data["python"] is True
    assert data["node"] is False
    assert data["pytest"] is True
    assert data["has_dockerfile"] is False
    assert data["has_ci"] is True  # SPEC deviation: ClawSeat has .github/workflows/ci.yml


def test_cartooner_medium_scan(tmp_path):
    """cartooner medium scan produces 6 granular + dev_env files."""
    _require_cartooner()
    _run_scan("cartooner", CARTOONER_REPO, "medium", tmp_path, commit=True)
    proj = tmp_path / "projects/cartooner"
    expected = ["dev_env.json", "runtime.json", "tests.json", "deploy.json", "ci.json", "lint.json", "structure.json"]
    for name in expected:
        assert (proj / name).exists(), f"missing {name}"
    runtime = json.loads((proj / "runtime.json").read_text())["data"]
    assert runtime["node"] is True
    assert runtime["pnpm"] is True
    assert runtime["python"] is True
    # python_version may be None (SPEC deviation: cartooner has no .python-version)


def test_cartooner_tests_frameworks(tmp_path):
    """cartooner tests.json contains pytest=True (vitest=False in reality)."""
    _require_cartooner()
    _run_scan("cartooner", CARTOONER_REPO, "medium", tmp_path, commit=True)
    tests = json.loads((tmp_path / "projects/cartooner/tests.json").read_text())["data"]
    assert tests["pytest"] is True
    # SPEC deviation: vitest=False — cartooner vitest config not found


def test_payload_budget_shallow(tmp_path):
    """ClawSeat shallow dev_env.json stays under 20KB."""
    _require_clawseat()
    dry = _run_scan("clawseat", CLAWSEAT_REPO, "shallow", tmp_path)
    payload = json.dumps(dry["files"]["dev_env.json"], ensure_ascii=False).encode()
    assert len(payload) <= 20 * 1024, f"shallow payload too large: {len(payload)}"


def test_payload_budget_medium(tmp_path):
    """cartooner medium 6 files total under 50KB."""
    _require_cartooner()
    dry = _run_scan("cartooner", CARTOONER_REPO, "medium", tmp_path)
    total = sum(
        len(json.dumps(rec, ensure_ascii=False).encode())
        for rec in dry["files"].values()
    )
    assert total <= 50 * 1024, f"medium payload too large: {total}"


def test_payload_budget_deep(tmp_path):
    """cartooner deep 7 files total under 70KB."""
    _require_cartooner()
    dry = _run_scan("cartooner", CARTOONER_REPO, "deep", tmp_path)
    assert "env_templates.json" in dry["files"], "deep must include env_templates.json"
    total = sum(
        len(json.dumps(rec, ensure_ascii=False).encode())
        for rec in dry["files"].values()
    )
    assert total <= 70 * 1024, f"deep payload too large: {total}"


def test_query_integration_runtime(tmp_path):
    """After committing a medium scan, query_memory returns valid runtime.json."""
    _require_cartooner()
    _run_scan("cartooner", CARTOONER_REPO, "medium", tmp_path, commit=True)
    facts = _run_query("cartooner", "runtime", tmp_path)
    assert isinstance(facts, list)
    assert len(facts) >= 1, "expected at least one runtime fact"
    rec = facts[0]
    assert rec.get("kind") == "runtime"
    assert isinstance(rec.get("data"), dict)
    assert rec["data"]  # non-empty


def test_query_integration_dev_env(tmp_path):
    """After committing a shallow scan, query_memory returns dev_env record."""
    _require_clawseat()
    _run_scan("clawseat", CLAWSEAT_REPO, "shallow", tmp_path, commit=True)
    facts = _run_query("clawseat", "dev_env", tmp_path)
    assert isinstance(facts, list)
    assert len(facts) >= 1
    assert facts[0]["kind"] == "dev_env"
    assert facts[0]["data"]["python"] is True


def test_dry_run_never_writes(tmp_path):
    """Default (no --commit) must not create any projects/ directory."""
    _require_clawseat()
    _run_scan("clawseat", CLAWSEAT_REPO, "shallow", tmp_path)
    assert not (tmp_path / "projects").exists(), "dry-run must not write projects/"
