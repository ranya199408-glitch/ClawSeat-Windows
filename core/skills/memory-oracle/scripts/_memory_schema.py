#!/usr/bin/env python3
"""
_memory_schema.py — schema v1 definition and validation for memory-oracle.

Schema (SPEC §4):
  {
    "schema_version": 1,
    "kind": "decision|delivery|issue|finding|reflection|library_knowledge|example|pattern|event",
    "id": "<kind>-<project|shared>-<hash>",
    "project": "<project-name> | _shared",
    "author": "planner | builder-1 | memory | ...",
    "ts": "2026-04-18T...",
    "title": "short",
    "body": "long-form (markdown ok)",
    "related_task_ids": ["T-001"],
    "evidence": [
      {"type": "commit|file|memory_id|url", "value": "...", "trust": "high|medium|low",
       "source_url": "..."}   ← required for library_knowledge and finding
    ],
    "supersedes": null,
    "confidence": "high|medium|low",
    "source": "scanner|write_api|reflection|event_derived|research"
  }

Hard rules (raise SchemaError):
  - schema_version == 1
  - kind in VALID_KINDS
  - ts matches ISO-8601 pattern
  - library_knowledge|finding: evidence[] non-empty, each item has trust + source_url

Soft rules (return warning strings, never raise):
  - author in known_authors list (if provided)
"""
from __future__ import annotations

import re
from typing import Any

VALID_KINDS: frozenset[str] = frozenset({
    # M1 kinds
    "decision",
    "delivery",
    "issue",
    "finding",
    "reflection",
    "library_knowledge",
    "example",
    "pattern",
    "event",
    # M2 project-scanner kinds
    "runtime",
    "tests",
    "deploy",
    "ci",
    "lint",
    "structure",
    "env_templates",
    "dev_env",
})

VALID_TRUST_LEVELS: frozenset[str] = frozenset({"high", "medium", "low"})
VALID_CONFIDENCE: frozenset[str] = frozenset({"high", "medium", "low"})
VALID_SOURCES: frozenset[str] = frozenset({
    "scanner", "write_api", "reflection", "event_derived", "research"
})

# Kinds that require non-empty evidence with trust + source_url on every item
EVIDENCE_REQUIRED_KINDS: frozenset[str] = frozenset({"library_knowledge", "finding"})

# ISO-8601: YYYY-MM-DDTHH:MM:SS with optional fractional seconds and timezone
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?$"
)


class SchemaError(ValueError):
    """Hard validation failure — the record must not be written."""


def _validate_ts(ts: Any) -> None:
    if not isinstance(ts, str):
        raise SchemaError(f"ts must be a string, got {type(ts).__name__!r}")
    if not _ISO8601_RE.match(ts):
        raise SchemaError(f"ts is not ISO-8601: {ts!r}")


def _validate_evidence(evidence: Any, kind: str) -> None:
    if not isinstance(evidence, list):
        raise SchemaError(f"evidence must be a list, got {type(evidence).__name__!r}")

    if kind not in EVIDENCE_REQUIRED_KINDS:
        return

    if not evidence:
        raise SchemaError(
            f"kind={kind!r} requires at least one evidence item (SPEC §4 decision 12)"
        )

    for i, ev in enumerate(evidence):
        if not isinstance(ev, dict):
            raise SchemaError(f"evidence[{i}] must be a dict, got {type(ev).__name__!r}")
        if "trust" not in ev:
            raise SchemaError(
                f"evidence[{i}] missing required field 'trust' for kind={kind!r}"
            )
        if "source_url" not in ev:
            raise SchemaError(
                f"evidence[{i}] missing required field 'source_url' for kind={kind!r}"
            )
        if ev["trust"] not in VALID_TRUST_LEVELS:
            raise SchemaError(
                f"evidence[{i}].trust must be one of {sorted(VALID_TRUST_LEVELS)}, "
                f"got {ev['trust']!r}"
            )


def validate(record: dict, *, known_authors: list[str] | None = None) -> list[str]:
    """Validate a fact record against schema v1.

    Returns:
        List of warning strings (soft violations — caller decides whether to surface them).

    Raises:
        SchemaError: on any hard validation failure; the record must not be written.

    Args:
        record: The fact dict to validate.
        known_authors: Optional whitelist of authorised seat names.  When
            provided and ``record["author"]`` is absent from the list, a
            warning is returned instead of raising (soft governance).
    """
    warnings: list[str] = []

    # ── Hard: schema_version ────────────────────────────────────────────
    sv = record.get("schema_version")
    if sv != 1:
        raise SchemaError(f"schema_version must be 1, got {sv!r}")

    # ── Hard: kind ──────────────────────────────────────────────────────
    kind = record.get("kind")
    if kind not in VALID_KINDS:
        raise SchemaError(
            f"kind {kind!r} not in whitelist {sorted(VALID_KINDS)}"
        )

    # ── Hard: ts ────────────────────────────────────────────────────────
    _validate_ts(record.get("ts"))

    # ── Hard: evidence (only for library_knowledge | finding) ───────────
    _validate_evidence(record.get("evidence", []), kind)  # type: ignore[arg-type]

    # ── Soft: author governance ──────────────────────────────────────────
    if known_authors is not None:
        author = record.get("author", "")
        if author not in known_authors:
            warnings.append(
                f"author {author!r} not in known seats {known_authors}; "
                "writing anyway (soft governance)"
            )

    return warnings


def make_record(
    *,
    kind: str,
    project: str,
    author: str,
    ts: str,
    title: str,
    fact_id: str,
    body: str = "",
    evidence: list[dict] | None = None,
    related_task_ids: list[str] | None = None,
    supersedes: str | None = None,
    confidence: str = "medium",
    source: str = "write_api",
) -> dict:
    """Build a canonical schema v1 record dict (does not validate — call validate() separately)."""
    return {
        "schema_version": 1,
        "kind": kind,
        "id": fact_id,
        "project": project,
        "author": author,
        "ts": ts,
        "title": title,
        "body": body,
        "related_task_ids": related_task_ids or [],
        "evidence": evidence or [],
        "supersedes": supersedes,
        "confidence": confidence,
        "source": source,
    }
