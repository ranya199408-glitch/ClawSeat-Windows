"""Tests for normalize_role handling of cartooner-* template role names.

cartooner-creative uses template-specific roles
(`cartooner-memory`, `cartooner-writer`, `cartooner-visual`, `cartooner-patrol`)
and gstack-harness should normalize them to canonical seat roles for routing logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "gstack-harness" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _common import normalize_role, role_sort_key  # noqa: E402


def test_normalize_cartooner_memory():
    assert normalize_role("cartooner-memory") == "memory"


def test_normalize_cartooner_writer():
    assert normalize_role("cartooner-writer") == "writer"


def test_normalize_cartooner_visual():
    assert normalize_role("cartooner-visual") == "visual"


def test_normalize_cartooner_patrol():
    assert normalize_role("cartooner-patrol") == "patrol"


def test_role_sort_key_cartooner_memory_matches_memory():
    assert role_sort_key("memory", "cartooner-memory") == role_sort_key("memory", "memory")


def test_role_sort_key_cartooner_writer_matches_writer():
    assert role_sort_key("writer", "cartooner-writer") == role_sort_key("writer", "writer")


def test_role_sort_key_cartooner_visual_matches_visual():
    assert role_sort_key("visual", "cartooner-visual") == role_sort_key("visual", "visual")


def test_role_sort_key_cartooner_patrol_matches_patrol():
    assert role_sort_key("patrol", "cartooner-patrol") == role_sort_key("patrol", "patrol")

