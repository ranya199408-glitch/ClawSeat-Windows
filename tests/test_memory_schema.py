"""Tests for _memory_schema.py — schema v1 validation.

Coverage:
  - schema_version hard check
  - kind whitelist hard check
  - ts ISO-8601 hard check
  - evidence required for library_knowledge and finding
  - evidence trust+source_url required for those kinds
  - trust value validation
  - author soft governance (warn, not reject)
  - make_record produces valid records
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from _memory_schema import (  # noqa: E402
    EVIDENCE_REQUIRED_KINDS,
    VALID_KINDS,
    VALID_TRUST_LEVELS,
    SchemaError,
    make_record,
    validate,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _base_record(**overrides) -> dict:
    rec = {
        "schema_version": 1,
        "kind": "decision",
        "id": "decision-install-abc12345",
        "project": "install",
        "author": "planner",
        "ts": "2026-04-18T10:00:00+00:00",
        "title": "Test decision",
        "body": "",
        "related_task_ids": [],
        "evidence": [],
        "supersedes": None,
        "confidence": "medium",
        "source": "write_api",
    }
    rec.update(overrides)
    return rec


def _evidence_item(**extra) -> dict:
    base = {"type": "file", "value": "SPEC.md", "trust": "high", "source_url": "https://example.com/spec"}
    base.update(extra)
    return base


# ── schema_version ────────────────────────────────────────────────────────────


def test_schema_version_1_passes():
    warnings = validate(_base_record())
    assert warnings == []


def test_schema_version_0_raises():
    with pytest.raises(SchemaError, match="schema_version"):
        validate(_base_record(schema_version=0))


def test_schema_version_2_raises():
    with pytest.raises(SchemaError, match="schema_version"):
        validate(_base_record(schema_version=2))


def test_schema_version_missing_raises():
    rec = _base_record()
    del rec["schema_version"]
    with pytest.raises(SchemaError, match="schema_version"):
        validate(rec)


def test_schema_version_string_raises():
    with pytest.raises(SchemaError, match="schema_version"):
        validate(_base_record(schema_version="1"))


# ── kind whitelist ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_all_valid_kinds_pass(kind):
    ev = [_evidence_item()] if kind in EVIDENCE_REQUIRED_KINDS else []
    warnings = validate(_base_record(kind=kind, evidence=ev))
    assert warnings == []


def test_invalid_kind_raises():
    with pytest.raises(SchemaError, match="kind"):
        validate(_base_record(kind="bogus"))


def test_kind_case_sensitive_raises():
    with pytest.raises(SchemaError, match="kind"):
        validate(_base_record(kind="Decision"))


def test_kind_empty_string_raises():
    with pytest.raises(SchemaError, match="kind"):
        validate(_base_record(kind=""))


def test_kind_none_raises():
    with pytest.raises(SchemaError, match="kind"):
        validate(_base_record(kind=None))


# ── ts ISO-8601 ───────────────────────────────────────────────────────────────


def test_ts_with_utc_offset_passes():
    warnings = validate(_base_record(ts="2026-04-18T10:00:00+00:00"))
    assert warnings == []


def test_ts_with_z_suffix_passes():
    warnings = validate(_base_record(ts="2026-04-18T10:00:00Z"))
    assert warnings == []


def test_ts_with_fractional_seconds_passes():
    warnings = validate(_base_record(ts="2026-04-18T10:00:00.123456+00:00"))
    assert warnings == []


def test_ts_without_timezone_passes():
    # ISO-8601 allows no timezone designator
    warnings = validate(_base_record(ts="2026-04-18T10:00:00"))
    assert warnings == []


def test_ts_date_only_raises():
    with pytest.raises(SchemaError, match="ISO-8601"):
        validate(_base_record(ts="2026-04-18"))


def test_ts_not_string_raises():
    with pytest.raises(SchemaError, match="ts must be a string"):
        validate(_base_record(ts=1745568000))


def test_ts_empty_string_raises():
    with pytest.raises(SchemaError, match="ISO-8601"):
        validate(_base_record(ts=""))


def test_ts_unix_epoch_raises():
    with pytest.raises(SchemaError, match="ISO-8601"):
        validate(_base_record(ts="1745568000"))


# ── evidence: kinds that require it ──────────────────────────────────────────


@pytest.mark.parametrize("kind", sorted(EVIDENCE_REQUIRED_KINDS))
def test_empty_evidence_for_required_kind_raises(kind):
    with pytest.raises(SchemaError, match="evidence"):
        validate(_base_record(kind=kind, evidence=[]))


@pytest.mark.parametrize("kind", sorted(EVIDENCE_REQUIRED_KINDS))
def test_missing_evidence_field_raises(kind):
    rec = _base_record(kind=kind)
    del rec["evidence"]
    with pytest.raises(SchemaError, match="evidence"):
        validate(rec)


@pytest.mark.parametrize("kind", sorted(EVIDENCE_REQUIRED_KINDS))
def test_evidence_without_trust_raises(kind):
    ev = [{"type": "url", "value": "https://example.com", "source_url": "https://example.com"}]
    with pytest.raises(SchemaError, match="trust"):
        validate(_base_record(kind=kind, evidence=ev))


@pytest.mark.parametrize("kind", sorted(EVIDENCE_REQUIRED_KINDS))
def test_evidence_without_source_url_raises(kind):
    ev = [{"type": "url", "value": "https://example.com", "trust": "high"}]
    with pytest.raises(SchemaError, match="source_url"):
        validate(_base_record(kind=kind, evidence=ev))


@pytest.mark.parametrize("kind", sorted(EVIDENCE_REQUIRED_KINDS))
def test_evidence_invalid_trust_raises(kind):
    ev = [_evidence_item(trust="very_high")]
    with pytest.raises(SchemaError, match="trust"):
        validate(_base_record(kind=kind, evidence=ev))


@pytest.mark.parametrize("kind", sorted(EVIDENCE_REQUIRED_KINDS))
def test_valid_evidence_passes(kind):
    ev = [_evidence_item()]
    warnings = validate(_base_record(kind=kind, evidence=ev))
    assert warnings == []


@pytest.mark.parametrize("trust", sorted(VALID_TRUST_LEVELS))
def test_all_trust_levels_pass(trust):
    ev = [_evidence_item(trust=trust)]
    warnings = validate(_base_record(kind="finding", evidence=ev))
    assert warnings == []


# ── evidence: kinds that don't require it ────────────────────────────────────


def test_empty_evidence_ok_for_decision():
    warnings = validate(_base_record(kind="decision", evidence=[]))
    assert warnings == []


def test_empty_evidence_ok_for_delivery():
    warnings = validate(_base_record(kind="delivery", evidence=[]))
    assert warnings == []


# ── soft governance: author ───────────────────────────────────────────────────


def test_author_in_seats_no_warning():
    warnings = validate(_base_record(author="planner"), known_authors=["planner", "builder-1"])
    assert warnings == []


def test_author_not_in_seats_produces_warning():
    warnings = validate(_base_record(author="intruder"), known_authors=["planner", "builder-1"])
    assert len(warnings) == 1
    assert "intruder" in warnings[0]
    assert "soft governance" in warnings[0]


def test_author_not_in_seats_does_not_raise():
    # Must not raise — soft governance only
    try:
        validate(_base_record(author="unknown"), known_authors=["planner"])
    except SchemaError:
        pytest.fail("SchemaError raised for unknown author — should be soft governance only")


def test_author_check_skipped_when_no_seats_provided():
    warnings = validate(_base_record(author="anyone"), known_authors=None)
    assert warnings == []


# ── make_record ───────────────────────────────────────────────────────────────


def test_make_record_produces_valid_record():
    rec = make_record(
        kind="decision",
        project="install",
        author="planner",
        ts="2026-04-18T10:00:00+00:00",
        title="Test",
        fact_id="decision-install-abc12345",
    )
    warnings = validate(rec)
    assert warnings == []
    assert rec["schema_version"] == 1
    assert rec["kind"] == "decision"


def test_make_record_defaults():
    rec = make_record(
        kind="issue",
        project="install",
        author="qa-1",
        ts="2026-04-18T10:00:00+00:00",
        title="Bug report",
        fact_id="issue-install-deadbeef",
    )
    assert rec["body"] == ""
    assert rec["related_task_ids"] == []
    assert rec["evidence"] == []
    assert rec["supersedes"] is None
    assert rec["confidence"] == "medium"
    assert rec["source"] == "write_api"
