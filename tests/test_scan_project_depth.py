"""Tests for scan_project.py depth gating and output matrix.

Coverage:
  - shallow → only dev_env.json
  - medium → dev_env + 6 granular files
  - deep → medium + env_templates
  - --depth defaults to shallow
  - Dry-run (default) returns valid JSON dict; does NOT write FS
  - --commit writes files; --force-commit overwrites
  - File existence validation: file count per depth
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
_SCAN_PY = _SCRIPTS / "scan_project.py"
sys.path.insert(0, str(_SCRIPTS))

from scan_project import scan, SHALLOW_KINDS, MEDIUM_KINDS, DEEP_KINDS  # noqa: E402


def make_python_repo(root: Path) -> Path:
    """Create a minimal Python repo fixture."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    return root


def run_scan(repo: Path, depth: str, memory_dir: Path, *extra_args) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable, str(_SCAN_PY),
        "--project", "testproj",
        "--repo", str(repo),
        "--depth", depth,
        "--memory-dir", str(memory_dir),
        "--quiet",
    ] + list(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


# ── Depth kind constants ───────────────────────────────────────────────────────


def test_shallow_kinds_contains_only_dev_env():
    assert set(SHALLOW_KINDS) == {"dev_env"}
    assert len(SHALLOW_KINDS) == 1


def test_medium_kinds_contains_six_granular_plus_dev_env():
    assert "dev_env" in MEDIUM_KINDS
    assert len(MEDIUM_KINDS) == 7


def test_deep_kinds_contains_env_templates_plus_medium():
    assert "env_templates" in DEEP_KINDS
    assert len(DEEP_KINDS) == 8


def test_medium_is_superset_of_shallow():
    assert set(SHALLOW_KINDS).issubset(set(MEDIUM_KINDS))


def test_deep_is_superset_of_medium():
    assert set(MEDIUM_KINDS).issubset(set(DEEP_KINDS))


# ── Dry-run mode (default) ────────────────────────────────────────────────────


def test_shallow_dryrun_prints_json(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = run_scan(repo, "shallow", tmp_path / "mem")
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["dry_run"] is True
    assert "dev_env.json" in output["files"]


def test_shallow_dryrun_does_not_write_files(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    run_scan(repo, "shallow", mem)
    projects_dir = mem / "projects" / "testproj"
    assert not projects_dir.exists()


def test_medium_dryrun_prints_seven_files(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = run_scan(repo, "medium", tmp_path / "mem")
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["files"]) == 7


def test_deep_dryrun_prints_eight_files(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = run_scan(repo, "deep", tmp_path / "mem")
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert len(output["files"]) == 8


def test_dryrun_output_is_valid_json(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = run_scan(repo, "medium", tmp_path / "mem")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)


def test_dryrun_records_have_schema_version_1(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = run_scan(repo, "shallow", tmp_path / "mem")
    output = json.loads(result.stdout)
    for fname, record in output["files"].items():
        assert record["schema_version"] == 1, f"Missing schema_version in {fname}"


def test_dryrun_contains_project_and_depth(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = run_scan(repo, "shallow", tmp_path / "mem")
    output = json.loads(result.stdout)
    assert output["project"] == "testproj"
    assert output["depth"] == "shallow"


# ── --commit writes correct files ─────────────────────────────────────────────


def test_shallow_commit_writes_exactly_one_file(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    result = run_scan(repo, "shallow", mem, "--commit")
    assert result.returncode == 0
    proj_dir = mem / "projects" / "testproj"
    files = [p.name for p in proj_dir.iterdir() if p.is_file()]
    assert files == ["dev_env.json"]


def test_medium_commit_writes_seven_files(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    result = run_scan(repo, "medium", mem, "--commit")
    assert result.returncode == 0
    proj_dir = mem / "projects" / "testproj"
    files = {p.name for p in proj_dir.iterdir() if p.is_file()}
    assert len(files) == 7
    assert "dev_env.json" in files
    assert "runtime.json" in files


def test_deep_commit_writes_eight_files(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    result = run_scan(repo, "deep", mem, "--commit")
    assert result.returncode == 0
    proj_dir = mem / "projects" / "testproj"
    files = {p.name for p in proj_dir.iterdir() if p.is_file()}
    assert len(files) == 8
    assert "env_templates.json" in files


def test_shallow_commit_dev_env_json_is_valid(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    run_scan(repo, "shallow", mem, "--commit")
    record = json.loads((mem / "projects" / "testproj" / "dev_env.json").read_text())
    assert record["kind"] == "dev_env"
    assert record["schema_version"] == 1
    assert "data" in record


def test_medium_specific_granular_files_exist(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    mem = tmp_path / "mem"
    run_scan(repo, "medium", mem, "--commit")
    proj_dir = mem / "projects" / "testproj"
    for kind in ("runtime", "tests", "deploy", "ci", "lint", "structure"):
        assert (proj_dir / f"{kind}.json").exists(), f"{kind}.json missing"


def test_default_depth_is_shallow(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    result = subprocess.run(
        [sys.executable, str(_SCAN_PY), "--project", "p", "--repo", str(repo),
         "--memory-dir", str(tmp_path / "mem"), "--commit", "--quiet"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    proj_dir = tmp_path / "mem" / "projects" / "p"
    files = [p.name for p in proj_dir.iterdir() if p.is_file()]
    assert files == ["dev_env.json"]


# ── Scan function API tests ────────────────────────────────────────────────────


def test_scan_function_shallow_returns_one_record(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="shallow", memory_root=tmp_path / "mem")
    assert set(records.keys()) == {"dev_env"}


def test_scan_function_medium_returns_seven_records(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="medium", memory_root=tmp_path / "mem")
    assert len(records) == 7


def test_scan_function_deep_returns_eight_records(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="deep", memory_root=tmp_path / "mem")
    assert len(records) == 8


def test_scan_function_all_records_have_schema_version(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="medium", memory_root=tmp_path / "mem")
    for kind, rec in records.items():
        assert rec["schema_version"] == 1, f"schema_version missing in {kind}"


def test_scan_function_dev_env_has_data_field(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="shallow", memory_root=tmp_path / "mem")
    assert "data" in records["dev_env"]


def test_scan_function_python_repo_has_python_true(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="shallow", memory_root=tmp_path / "mem")
    assert records["dev_env"]["data"]["python"] is True


def test_scan_function_evidence_in_all_records(tmp_path):
    repo = make_python_repo(tmp_path / "repo")
    records = scan("myproj", repo, depth="medium", memory_root=tmp_path / "mem")
    for kind, rec in records.items():
        assert rec.get("evidence"), f"evidence missing in {kind}"
        for ev in rec["evidence"]:
            assert "source_url" in ev
            assert "trust" in ev
