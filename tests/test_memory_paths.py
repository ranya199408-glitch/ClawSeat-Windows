"""Tests for _memory_paths.py — path constants and helpers.

Coverage (F1 reviewer finding):
  - REFLECTIONS_FILE constant is 'reflections.jsonl'
  - EVENTS_LOG points to <memory_root>/events.log
  - reflections_path() returns projects/<proj>/reflections.jsonl
  - events_log_path() returns <memory_root>/events.log
  - reflections_path() and events_log_path() respect memory_root override
  - fact_path() for kind=reflection routes to reflections.jsonl
  - fact_path() for kind=decision still returns a JSON path
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

from _memory_paths import (  # noqa: E402
    EVENTS_LOG,
    MEMORY_ROOT,
    REFLECTIONS_FILE,
    events_log_path,
    fact_path,
    generate_id,
    reflections_path,
)


# ── REFLECTIONS_FILE constant ─────────────────────────────────────────────────


def test_reflections_file_constant():
    assert REFLECTIONS_FILE == "reflections.jsonl"


# ── reflections_path() ────────────────────────────────────────────────────────


def test_reflections_path_default_root():
    p = reflections_path("install")
    assert p == MEMORY_ROOT / "projects" / "install" / "reflections.jsonl"


def test_reflections_path_custom_root(tmp_path):
    p = reflections_path("myproject", memory_root=tmp_path)
    assert p == tmp_path / "projects" / "myproject" / "reflections.jsonl"
    assert p.name == "reflections.jsonl"


def test_reflections_path_different_projects(tmp_path):
    p1 = reflections_path("install", memory_root=tmp_path)
    p2 = reflections_path("other", memory_root=tmp_path)
    assert p1 != p2
    assert p1.parent.name == "install"
    assert p2.parent.name == "other"


# ── events_log_path() ────────────────────────────────────────────────────────


def test_events_log_path_default_root():
    p = events_log_path()
    assert p == MEMORY_ROOT / "events.log"


def test_events_log_path_custom_root(tmp_path):
    p = events_log_path(memory_root=tmp_path)
    assert p == tmp_path / "events.log"
    assert p.name == "events.log"


def test_events_log_constant_matches_helper():
    assert EVENTS_LOG == events_log_path()


# ── fact_path() routing for reflection ───────────────────────────────────────


def test_fact_path_reflection_routes_to_jsonl(tmp_path):
    p = fact_path("reflection", "install", "reflection-install-abc", memory_root=tmp_path)
    assert p == tmp_path / "projects" / "install" / "reflections.jsonl"


def test_fact_path_reflection_is_jsonl_not_json(tmp_path):
    p = fact_path("reflection", "install", "reflection-install-abc", memory_root=tmp_path)
    assert p.suffix == ".jsonl"


def test_fact_path_decision_is_json_not_jsonl(tmp_path):
    p = fact_path("decision", "install", "decision-install-abc", memory_root=tmp_path)
    assert p.suffix == ".json"
    assert "decisions" in str(p)


def test_fact_path_decision_not_affected(tmp_path):
    p = fact_path("decision", "install", "decision-install-abc", memory_root=tmp_path)
    assert p == tmp_path / "projects" / "install" / "decisions" / "decision-install-abc.json"


def test_fact_path_delivery_not_affected(tmp_path):
    p = fact_path("delivery", "install", "delivery-install-xyz", memory_root=tmp_path)
    assert p == tmp_path / "projects" / "install" / "deliveries" / "delivery-install-xyz.json"


def test_fact_path_finding_not_affected(tmp_path):
    p = fact_path("finding", "install", "finding-install-xyz", memory_root=tmp_path)
    assert p == tmp_path / "projects" / "install" / "findings" / "finding-install-xyz.json"


# ── generate_id() still works ────────────────────────────────────────────────


def test_generate_id_format():
    fact_id = generate_id("decision", "install", "Test title")
    parts = fact_id.split("-")
    assert parts[0] == "decision"
    assert parts[1] == "install"
    assert len(parts[2]) == 8


def test_generate_id_shared():
    fact_id = generate_id("library_knowledge", "_shared", "pytest tips")
    assert fact_id.startswith("library_knowledge-shared-")
