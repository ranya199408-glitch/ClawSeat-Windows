"""Tests for memory_write.py — fact writing CLI.

Coverage:
  - All valid kinds write to correct subdirectory
  - Soft governance: unknown author still writes but stdout has warning
  - Hard validation failures exit 1 without writing
  - Bad JSON --evidence exits 2
  - --dry-run validates but does not write
  - Projects layout: decisions/, deliveries/, issues/, findings/
  - _shared project writes to shared/ subtree
  - Output JSON contains id, path, warnings fields
  - ID format: <kind>-<project>-<hash>
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
_WRITE_PY = _SCRIPTS / "memory_write.py"
sys.path.insert(0, str(_SCRIPTS))

from _memory_paths import KIND_SUBDIRS, SHARED_KIND_SUBDIRS  # noqa: E402
from _memory_schema import VALID_KINDS  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


def run_write(*extra_args: str, memory_dir: str, capture_stderr: bool = True) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_WRITE_PY),
        "--memory-dir", memory_dir,
    ] + list(extra_args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )


def minimal_args(kind: str, project: str = "install", title: str = "Test fact") -> list[str]:
    return [
        "--kind", kind,
        "--project", project,
        "--title", title,
        "--author", "planner",
    ]


def evidence_json(*, trust: str = "high") -> str:
    return json.dumps([{
        "type": "file",
        "value": "SPEC.md",
        "trust": trust,
        "source_url": "https://example.com/spec",
    }])


# ── Valid kinds write to disk ─────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_valid_kind_writes_file(kind, tmp_path):
    ev = evidence_json() if kind in {"library_knowledge", "finding"} else "[]"
    result = run_write(
        *minimal_args(kind),
        "--evidence", ev,
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"

    out = json.loads(result.stdout)
    path = Path(out["path"])
    assert path.exists(), f"file not written: {path}"

    record = json.loads(path.read_text())
    assert record["kind"] == kind
    assert record["schema_version"] == 1


def test_decision_goes_to_decisions_subdir(tmp_path):
    result = run_write(*minimal_args("decision"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "/projects/install/decisions/" in out["path"]


def test_delivery_goes_to_deliveries_subdir(tmp_path):
    result = run_write(*minimal_args("delivery"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "/projects/install/deliveries/" in out["path"]


def test_issue_goes_to_issues_subdir(tmp_path):
    result = run_write(*minimal_args("issue"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "/projects/install/issues/" in out["path"]


def test_finding_goes_to_findings_subdir(tmp_path):
    result = run_write(
        *minimal_args("finding"),
        "--evidence", evidence_json(),
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "/projects/install/findings/" in out["path"]


def test_library_knowledge_goes_to_shared_subdir(tmp_path):
    result = run_write(
        "--kind", "library_knowledge",
        "--project", "_shared",
        "--title", "pytest tips",
        "--author", "memory",
        "--evidence", evidence_json(),
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "/shared/library_knowledge/" in out["path"]


# ── ID format ────────────────────────────────────────────────────────────────


def test_id_format_is_kind_project_hash(tmp_path):
    result = run_write(*minimal_args("decision", project="myproject"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    fact_id = out["id"]
    parts = fact_id.split("-")
    assert parts[0] == "decision"
    assert parts[1] == "myproject"
    assert len(parts[2]) == 8  # 8-char hex hash


def test_shared_project_id_uses_shared_namespace(tmp_path):
    result = run_write(
        "--kind", "library_knowledge",
        "--project", "_shared",
        "--title", "Some knowledge",
        "--author", "memory",
        "--evidence", evidence_json(),
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["id"].startswith("library_knowledge-shared-")


# ── Written record contents ───────────────────────────────────────────────────


def test_written_record_has_correct_fields(tmp_path):
    result = run_write(
        "--kind", "decision",
        "--project", "install",
        "--title", "My decision",
        "--body", "Some body text",
        "--author", "planner",
        "--confidence", "high",
        "--source", "write_api",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    record = json.loads(Path(out["path"]).read_text())
    assert record["title"] == "My decision"
    assert record["body"] == "Some body text"
    assert record["author"] == "planner"
    assert record["confidence"] == "high"
    assert record["source"] == "write_api"
    assert record["project"] == "install"


def test_related_task_ids_written_correctly(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--related-task-ids", "T-001,T-002",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    record = json.loads(Path(out["path"]).read_text())
    assert record["related_task_ids"] == ["T-001", "T-002"]


def test_supersedes_written_correctly(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--supersedes", "decision-install-oldid",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    record = json.loads(Path(out["path"]).read_text())
    assert record["supersedes"] == "decision-install-oldid"


# ── Soft governance: author not in seats ─────────────────────────────────────


def test_unknown_author_writes_with_warning(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--author", "rogue-agent",
        "--seats", "planner,builder-1",
        memory_dir=str(tmp_path),
    )
    # Must not fail — soft governance
    assert result.returncode == 0
    # Warning must appear on stderr
    assert "warning" in result.stderr.lower()
    assert "rogue-agent" in result.stderr
    # File must still be written
    out = json.loads(result.stdout)
    assert Path(out["path"]).exists()


def test_unknown_author_warning_in_output_warnings_list(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--author", "rogue-agent",
        "--seats", "planner,builder-1",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert len(out["warnings"]) > 0
    assert any("rogue-agent" in w for w in out["warnings"])


def test_known_author_no_warning(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--author", "planner",
        "--seats", "planner,builder-1",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["warnings"] == []


# ── Hard validation failures ──────────────────────────────────────────────────


def test_invalid_kind_exits_1(tmp_path):
    result = run_write(
        "--kind", "bogus",
        "--project", "install",
        "--title", "x",
        "--author", "planner",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 1
    assert "error" in result.stderr.lower()


def test_finding_without_evidence_exits_1(tmp_path):
    result = run_write(
        "--kind", "finding",
        "--project", "install",
        "--title", "Finding without evidence",
        "--author", "builder-1",
        "--evidence", "[]",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 1
    assert "evidence" in result.stderr.lower()


def test_library_knowledge_evidence_without_source_url_exits_1(tmp_path):
    ev = json.dumps([{"type": "url", "value": "https://x.com", "trust": "high"}])
    result = run_write(
        "--kind", "library_knowledge",
        "--project", "_shared",
        "--title", "Some knowledge",
        "--author", "memory",
        "--evidence", ev,
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 1
    assert "source_url" in result.stderr


def test_finding_evidence_invalid_trust_exits_1(tmp_path):
    ev = json.dumps([{"type": "url", "value": "https://x.com", "trust": "extreme", "source_url": "https://x.com"}])
    result = run_write(
        "--kind", "finding",
        "--project", "install",
        "--title", "x",
        "--author", "builder-1",
        "--evidence", ev,
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 1


# ── Bad JSON --evidence ───────────────────────────────────────────────────────


def test_invalid_evidence_json_exits_2(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--evidence", "not-json",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 2


def test_evidence_not_array_exits_2(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--evidence", '{"type": "file"}',
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 2


# ── --dry-run ─────────────────────────────────────────────────────────────────


def test_dry_run_does_not_write_file(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--dry-run",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    projects_dir = tmp_path / "projects"
    assert not projects_dir.exists()


def test_dry_run_prints_record_json(tmp_path):
    result = run_write(
        *minimal_args("decision"),
        "--dry-run",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    record = json.loads(result.stdout)
    assert record["kind"] == "decision"
    assert record["schema_version"] == 1


def test_dry_run_invalid_kind_exits_1(tmp_path):
    result = run_write(
        "--kind", "invalid",
        "--project", "install",
        "--title", "x",
        "--author", "planner",
        "--dry-run",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 1


# ── Output JSON structure ─────────────────────────────────────────────────────


def test_output_contains_id_path_warnings(tmp_path):
    result = run_write(*minimal_args("decision"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "id" in out
    assert "path" in out
    assert "warnings" in out
    assert isinstance(out["warnings"], list)


# ── File permissions ──────────────────────────────────────────────────────────


def test_written_file_permissions_are_600(tmp_path):
    import stat

    result = run_write(*minimal_args("decision"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    p = Path(out["path"])
    mode = p.stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


# ── kind=reflection → JSONL append ───────────────────────────────────────────


def test_reflection_writes_to_reflections_jsonl(tmp_path):
    result = run_write(*minimal_args("reflection"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["path"].endswith("reflections.jsonl"), f"Expected reflections.jsonl, got {out['path']}"


def test_reflection_path_contains_project_dir(tmp_path):
    result = run_write(*minimal_args("reflection", project="install"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert "/projects/install/reflections.jsonl" in out["path"]


def test_reflection_two_writes_produce_two_jsonl_lines(tmp_path):
    run_write(*minimal_args("reflection", title="First thought"), memory_dir=str(tmp_path))
    run_write(*minimal_args("reflection", title="Second thought"), memory_dir=str(tmp_path))
    jsonl_file = tmp_path / "projects" / "install" / "reflections.jsonl"
    assert jsonl_file.exists()
    lines = [l for l in jsonl_file.read_text().splitlines() if l.strip()]
    assert len(lines) == 2


def test_reflection_jsonl_lines_are_valid_json(tmp_path):
    run_write(*minimal_args("reflection", title="Alpha"), memory_dir=str(tmp_path))
    run_write(*minimal_args("reflection", title="Beta"), memory_dir=str(tmp_path))
    jsonl_file = tmp_path / "projects" / "install" / "reflections.jsonl"
    lines = [l for l in jsonl_file.read_text().splitlines() if l.strip()]
    for line in lines:
        record = json.loads(line)
        assert record["kind"] == "reflection"
        assert record["schema_version"] == 1


def test_reflection_jsonl_records_have_distinct_ids(tmp_path):
    run_write(*minimal_args("reflection", title="Alpha"), memory_dir=str(tmp_path))
    run_write(*minimal_args("reflection", title="Beta"), memory_dir=str(tmp_path))
    jsonl_file = tmp_path / "projects" / "install" / "reflections.jsonl"
    lines = [l for l in jsonl_file.read_text().splitlines() if l.strip()]
    ids = [json.loads(l)["id"] for l in lines]
    assert len(set(ids)) == 2


def test_reflection_does_not_write_id_json_file(tmp_path):
    result = run_write(*minimal_args("reflection"), memory_dir=str(tmp_path))
    assert result.returncode == 0
    project_root = tmp_path / "projects" / "install"
    json_files = list(project_root.glob("reflection-*.json"))
    assert json_files == [], f"Unexpected .json files: {json_files}"


def test_reflection_no_loose_json_at_project_root(tmp_path):
    run_write(*minimal_args("reflection", title="Alpha"), memory_dir=str(tmp_path))
    run_write(*minimal_args("reflection", title="Beta"), memory_dir=str(tmp_path))
    project_root = tmp_path / "projects" / "install"
    loose_json = [p for p in project_root.glob("*.json")]
    assert loose_json == [], f"Loose .json files at project root: {loose_json}"


def test_reflection_schema_validated_before_jsonl_write(tmp_path):
    result = run_write(
        "--kind", "reflection",
        "--project", "install",
        "--title", "x",
        "--author", "planner",
        "--seats", "planner,builder-1",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    jsonl_file = tmp_path / "projects" / "install" / "reflections.jsonl"
    assert jsonl_file.exists()


def test_reflection_author_soft_governance_still_applies(tmp_path):
    result = run_write(
        "--kind", "reflection",
        "--project", "install",
        "--title", "Soft check",
        "--author", "unknown-bot",
        "--seats", "planner,builder-1",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    assert "warning" in result.stderr.lower()
    jsonl_file = tmp_path / "projects" / "install" / "reflections.jsonl"
    assert jsonl_file.exists()


def test_reflection_dry_run_does_not_write_jsonl(tmp_path):
    result = run_write(
        *minimal_args("reflection"),
        "--dry-run",
        memory_dir=str(tmp_path),
    )
    assert result.returncode == 0
    jsonl_file = tmp_path / "projects" / "install" / "reflections.jsonl"
    assert not jsonl_file.exists()
