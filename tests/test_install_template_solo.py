from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


_REPO = Path(__file__).resolve().parents[1]


def _solo() -> dict:
    return tomllib.loads((_REPO / "templates" / "clawseat-solo.toml").read_text(encoding="utf-8"))


def test_solo_template_loads() -> None:
    """clawseat-solo.toml loads with memory, builder, planner."""
    data = _solo()
    assert len(data["engineers"]) == 3
    assert data["defaults"]["window_mode"] == "split-2"
    assert data["defaults"]["monitor_max_panes"] == 3
    ids = {e["id"] for e in data["engineers"]}
    assert ids == {"memory", "builder", "planner"}


def test_solo_memory_hands_off_to_planner() -> None:
    """memory retains planner SKILL context but no longer absorbs planner orchestration."""
    data = _solo()
    mem = next(e for e in data["engineers"] if e["id"] == "memory")
    assert mem["active_loop_owner"] is False
    assert mem["dispatch_authority"] is False
    skill_paths = " ".join(mem["skills"])
    assert "planner/SKILL.md" in skill_paths
    assert len(mem["skills"]) == 11
    assert ("SWA" + "LLOW") not in " ".join(mem.get("role_details", []))
    builder = next(e for e in data["engineers"] if e["id"] == "builder")
    assert builder["tool"] == "codex"
    assert builder["auth_mode"] == "oauth"
    assert len(builder["skills"]) == 3
    planner = next(e for e in data["engineers"] if e["id"] == "planner")
    assert planner["tool"] == "gemini"
    assert planner["auth_mode"] == "oauth"
    assert planner["provider"] == "google"
    assert planner["active_loop_owner"] is True
    assert planner["dispatch_authority"] is True
    assert len(planner["skills"]) == 3
