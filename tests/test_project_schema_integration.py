"""Tests for M2 schema integration — new kinds pass M1 schema validator.

Coverage:
  - All 8 new M2 kinds accepted by _memory_schema.validate()
  - All 9 M1 kinds still accepted (regression guard)
  - VALID_KINDS now has 17 elements
  - EVIDENCE_REQUIRED_KINDS unchanged (still only library_knowledge + finding)
  - author/ts/evidence/source_url/trust validations unchanged
  - Schema v1 records with M2 kinds can be written and read back
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from _memory_schema import (  # noqa: E402
    VALID_KINDS,
    EVIDENCE_REQUIRED_KINDS,
    SchemaError,
    make_record,
    validate,
)
from _memory_paths import generate_id  # noqa: E402


M1_KINDS = frozenset({
    "decision", "delivery", "issue", "finding", "reflection",
    "library_knowledge", "example", "pattern", "event",
})

M2_KINDS = frozenset({
    "runtime", "tests", "deploy", "ci", "lint",
    "structure", "env_templates", "dev_env",
})


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record(kind: str, **kwargs) -> dict:
    project = kwargs.pop("project", "myproject")
    fact_id = generate_id(kind, project, "test")
    ev = kwargs.pop("evidence", [])
    return make_record(
        kind=kind,
        project=project,
        author="memory",
        ts=_ts(),
        title=f"Test {kind}",
        fact_id=fact_id,
        evidence=ev,
        **kwargs,
    )


# ── VALID_KINDS size ──────────────────────────────────────────────────────────


def test_valid_kinds_has_17_elements():
    assert len(VALID_KINDS) == 17, f"Expected 17, got {len(VALID_KINDS)}: {sorted(VALID_KINDS)}"


def test_valid_kinds_contains_all_m1_kinds():
    assert M1_KINDS.issubset(VALID_KINDS)


def test_valid_kinds_contains_all_m2_kinds():
    assert M2_KINDS.issubset(VALID_KINDS)


# ── M2 kinds pass validation ──────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(M2_KINDS))
def test_m2_kind_passes_validation(kind):
    rec = _record(kind)
    warnings = validate(rec)
    assert isinstance(warnings, list)


@pytest.mark.parametrize("kind", sorted(M2_KINDS))
def test_m2_kind_record_has_schema_version_1(kind):
    rec = _record(kind)
    assert rec["schema_version"] == 1


@pytest.mark.parametrize("kind", sorted(M2_KINDS))
def test_m2_kind_in_valid_kinds(kind):
    assert kind in VALID_KINDS


# ── M1 kinds still pass validation (regression guard) ────────────────────────


@pytest.mark.parametrize("kind", sorted(M1_KINDS - EVIDENCE_REQUIRED_KINDS))
def test_m1_kind_still_passes_validation(kind):
    rec = _record(kind)
    warnings = validate(rec)
    assert isinstance(warnings, list)


def test_m1_library_knowledge_still_requires_evidence():
    rec = _record("library_knowledge", evidence=[])
    with pytest.raises(SchemaError, match="evidence"):
        validate(rec)


def test_m1_finding_still_requires_evidence():
    rec = _record("finding", evidence=[])
    with pytest.raises(SchemaError, match="evidence"):
        validate(rec)


def test_m1_finding_with_evidence_passes():
    ev = [{"source_url": "https://example.com", "trust": "high"}]
    rec = _record("finding", evidence=ev)
    warnings = validate(rec)
    assert isinstance(warnings, list)


# ── EVIDENCE_REQUIRED_KINDS unchanged ────────────────────────────────────────


def test_evidence_required_kinds_unchanged():
    assert EVIDENCE_REQUIRED_KINDS == frozenset({"library_knowledge", "finding"})


def test_m2_runtime_does_not_require_evidence():
    rec = _record("runtime", evidence=[])
    warnings = validate(rec)
    assert isinstance(warnings, list)


def test_m2_dev_env_does_not_require_evidence():
    rec = _record("dev_env", evidence=[])
    warnings = validate(rec)
    assert isinstance(warnings, list)


# ── Schema hard rules still apply to M2 kinds ────────────────────────────────


def test_m2_kind_schema_version_0_rejected():
    rec = _record("runtime")
    rec["schema_version"] = 0
    with pytest.raises(SchemaError, match="schema_version"):
        validate(rec)


def test_m2_kind_invalid_ts_rejected():
    rec = _record("dev_env")
    rec["ts"] = "not-a-timestamp"
    with pytest.raises(SchemaError, match="ISO-8601"):
        validate(rec)


def test_unknown_m2_adjacent_kind_rejected():
    rec = _record("runtime")
    rec["kind"] = "not_a_real_kind"
    with pytest.raises(SchemaError, match="whitelist"):
        validate(rec)


# ── Author soft governance still applies to M2 ───────────────────────────────


def test_m2_unknown_author_produces_warning():
    rec = _record("dev_env")
    warnings = validate(rec, known_authors=["planner", "builder-1"])
    assert len(warnings) == 1
    assert "memory" in warnings[0]


def test_m2_known_author_no_warning():
    rec = _record("dev_env")
    warnings = validate(rec, known_authors=["memory", "planner"])
    assert warnings == []


# ── M2 record roundtrip via make_record ───────────────────────────────────────


def test_m2_runtime_record_roundtrip():
    ts = _ts()
    fact_id = generate_id("runtime", "proj", "x")
    rec = make_record(
        kind="runtime",
        project="proj",
        author="memory",
        ts=ts,
        title="proj runtime scan",
        fact_id=fact_id,
        source="scanner",
        confidence="high",
    )
    assert rec["kind"] == "runtime"
    assert rec["project"] == "proj"
    assert rec["author"] == "memory"
    warnings = validate(rec)
    assert isinstance(warnings, list)


def test_m2_dev_env_with_data_field_passes():
    ts = _ts()
    fact_id = generate_id("dev_env", "proj", "x")
    rec = make_record(
        kind="dev_env",
        project="proj",
        author="memory",
        ts=ts,
        title="dev_env summary",
        fact_id=fact_id,
        source="scanner",
    )
    rec["data"] = {"python": True, "node": False}
    warnings = validate(rec)
    assert isinstance(warnings, list)
