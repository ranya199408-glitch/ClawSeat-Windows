"""Tests for _resolve_gstack_skills_root() in dispatch_task.py.

Verifies env-var precedence, home-convention fallback, empty-string fallback,
INTENT_MAP propagation, and absence of any /Users/* hardcode in the source.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "gstack-harness" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import dispatch_task  # noqa: E402


def _reload(monkeypatch_fn=None):
    """Reload dispatch_task so module-level _GSTACK_SKILLS_ROOT is re-evaluated."""
    if "dispatch_task" in sys.modules:
        del sys.modules["dispatch_task"]
    return importlib.import_module("dispatch_task")


def test_env_var_takes_precedence(monkeypatch):
    """GSTACK_SKILLS_ROOT env var is returned as-is when set to a non-empty value."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "/custom/path")
    import dispatch_task as dt
    assert dt._resolve_gstack_skills_root() == "/custom/path"


def test_home_default_when_env_unset(monkeypatch, tmp_path):
    """When GSTACK_SKILLS_ROOT is unset, path is constructed from real user HOME."""
    monkeypatch.delenv("GSTACK_SKILLS_ROOT", raising=False)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    import dispatch_task as dt
    result = dt._resolve_gstack_skills_root()
    expected = str(tmp_path / ".gstack" / "repos" / "gstack" / ".agents" / "skills")
    assert result == expected


def test_env_var_empty_string_falls_to_default(monkeypatch, tmp_path):
    """An empty GSTACK_SKILLS_ROOT is treated as unset — home default applies."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "")
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    import dispatch_task as dt
    result = dt._resolve_gstack_skills_root()
    assert result != ""
    assert ".gstack" in result


def test_intent_map_skill_md_uses_resolved_root(monkeypatch):
    """After reload with custom GSTACK_SKILLS_ROOT, INTENT_MAP skill_md values reflect it."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "/test/skills")
    mod = _reload()
    for intent, entry in mod.INTENT_MAP.items():
        assert entry["skill_md"].startswith("/test/skills"), (
            f"INTENT_MAP[{intent!r}]['skill_md'] does not start with /test/skills: "
            f"{entry['skill_md']!r}"
        )


def test_no_hardcoded_user_path_in_source():
    """dispatch_task.py source must not contain any /Users/ absolute path."""
    source = (_SCRIPTS / "dispatch_task.py").read_text(encoding="utf-8")
    hits = [ln for ln in source.splitlines() if "/Users/" in ln]
    assert hits == [], f"Found /Users/ hardcode(s):\n" + "\n".join(hits)
