"""Regression: preflight's gstack check is HARD_BLOCKED when the active
profile declares a specialist role (builder / reviewer / patrol / designer),
and WARNING otherwise.

Before the UX-audit fix, preflight always returned WARNING for missing
gstack even though downstream bootstrap helpers would later exit non-zero on
the same missing skills. A stranger installer hit a "ladder of mysterious
failures": preflight green-lighted them, then the next script blew up with a
cryptic skill-registry error.

The fix: preflight now loads the profile's seat_roles and HARD_BLOCKS if
any role actually needs gstack. This test locks that behavior so a
future refactor can't accidentally revert to the always-WARNING class.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tomllib
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _load_preflight():
    """Fresh-import core/preflight.py (has its own sys.path bootstrap)."""
    spec = importlib.util.spec_from_file_location(
        "preflight_under_test", _REPO / "core" / "preflight.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["preflight_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_profile(tmp_path: Path, project: str, seat_roles: dict[str, str]) -> Path:
    """Write a minimal dynamic profile with the given seat_roles mapping."""
    profile_path = tmp_path / f"{project}-profile-dynamic.toml"
    body_lines = [
        f'project_name = "{project}"',
        'tasks_root = "~/.agents/tasks/%s"' % project,
        "[seat_roles]",
    ]
    for seat, role in seat_roles.items():
        body_lines.append(f'"{seat}" = "{role}"')
    profile_path.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return profile_path


def test_gstack_missing_hardblocks_when_builder_role_declared(monkeypatch, tmp_path):
    """Profile with builder role → gstack missing must HARD_BLOCK."""
    profile = _write_profile(tmp_path, "t1", {"koder": "frontstage-supervisor", "builder-1": "builder"})
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "nope"))  # guaranteed missing
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)  # isolate $HOME
    # redirect the dynamic-profile resolver to our tmp file
    mod = _load_preflight()
    monkeypatch.setattr(mod, "_dynamic_profile_path", lambda project: profile)

    result = mod.preflight_check("t1")
    gstack_items = [i for i in result.items if i.name == "gstack"]
    assert gstack_items, "preflight must emit a gstack item"
    assert gstack_items[0].status == mod.PreflightStatus.HARD_BLOCKED, (
        f"expected HARD_BLOCKED (builder role present), got {gstack_items[0].status}:\n"
        f"  message: {gstack_items[0].message}"
    )
    # Message must name the specialist role so operator knows WHY it's blocked
    assert "builder" in gstack_items[0].message, gstack_items[0].message


def test_gstack_missing_warns_only_when_no_specialist_roles(monkeypatch, tmp_path):
    """Profile with only frontstage-supervisor (koder-only) → gstack missing is WARNING only."""
    profile = _write_profile(tmp_path, "t2", {"koder": "frontstage-supervisor"})
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "nope"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    mod = _load_preflight()
    monkeypatch.setattr(mod, "_dynamic_profile_path", lambda project: profile)

    result = mod.preflight_check("t2")
    gstack_items = [i for i in result.items if i.name == "gstack"]
    assert gstack_items, "preflight must still emit a gstack item"
    assert gstack_items[0].status == mod.PreflightStatus.WARNING, (
        f"expected WARNING (no specialist roles), got {gstack_items[0].status}:\n"
        f"  message: {gstack_items[0].message}"
    )


def test_gstack_missing_warns_when_profile_unreadable(monkeypatch, tmp_path):
    """Profile not on disk → active_roles is None → gstack missing falls back to WARNING.

    This matches the pre-audit default so we don't break preflight invocations
    that run before bootstrap has written the dynamic profile.
    """
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "nope"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    mod = _load_preflight()
    monkeypatch.setattr(mod, "_dynamic_profile_path", lambda project: tmp_path / "absent.toml")

    result = mod.preflight_check("t3")
    gstack_items = [i for i in result.items if i.name == "gstack"]
    assert gstack_items
    assert gstack_items[0].status == mod.PreflightStatus.WARNING, (
        f"unreadable profile → should default to WARN, got {gstack_items[0].status}"
    )


def test_gstack_all_specialist_roles_trigger_hardblock(monkeypatch, tmp_path):
    """Each of {builder, reviewer, patrol, designer} independently must trip HARD_BLOCKED."""
    for role in ("builder", "reviewer", "patrol", "designer"):
        profile = _write_profile(tmp_path, f"t-{role}", {"koder": "frontstage-supervisor", f"{role}-1": role})
        monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "nope"))
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mod = _load_preflight()
        monkeypatch.setattr(mod, "_dynamic_profile_path", lambda project: profile)

        result = mod.preflight_check(f"t-{role}")
        gstack_items = [i for i in result.items if i.name == "gstack"]
        assert gstack_items
        assert gstack_items[0].status == mod.PreflightStatus.HARD_BLOCKED, (
            f"role {role} should HARD_BLOCK gstack, got {gstack_items[0].status}"
        )


def test_gstack_fix_command_includes_both_paths(monkeypatch, tmp_path):
    """The fix_command must mention both the canonical clone AND the
    GSTACK_SKILLS_ROOT env var so a stranger picks the right one."""
    profile = _write_profile(tmp_path, "t5", {"koder": "frontstage-supervisor"})
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "nope"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    mod = _load_preflight()
    monkeypatch.setattr(mod, "_dynamic_profile_path", lambda project: profile)

    result = mod.preflight_check("t5")
    gstack_items = [i for i in result.items if i.name == "gstack"]
    assert gstack_items
    fix = gstack_items[0].fix_command
    assert "git clone" in fix and "garrytan/gstack" in fix, "missing canonical clone hint"
    assert "GSTACK_SKILLS_ROOT" in fix, "missing env-var fallback hint"
    assert "Path checked" in fix, "operator needs to see exact path examined"


def test_relative_gstack_env_hardblocks_regardless_of_profile(monkeypatch, tmp_path):
    """Non-absolute GSTACK_SKILLS_ROOT must HARD_BLOCK preflight *before*
    the existence check, so the operator learns their env var was junk
    instead of debugging a mystery 'skills not found at ./skills' error.

    Applies even to koder-only profiles — the operator's expressed intent
    was to override, and we should surface that the override is broken.
    """
    profile = _write_profile(tmp_path, "t6", {"koder": "frontstage-supervisor"})
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "./nope-relative")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    mod = _load_preflight()
    monkeypatch.setattr(mod, "_dynamic_profile_path", lambda project: profile)

    result = mod.preflight_check("t6")
    gstack_items = [i for i in result.items if i.name == "gstack"]
    # Should have TWO items: the HARD_BLOCK for non-absolute env, and the
    # fallthrough WARN/HARD for canonical missing. We only assert that at
    # least one is HARD_BLOCKED and its message names the bad env value.
    hard = [i for i in gstack_items if i.status == mod.PreflightStatus.HARD_BLOCKED]
    assert hard, (
        f"expected HARD_BLOCKED from non-absolute env, got {[i.status for i in gstack_items]}"
    )
    assert any("not an absolute path" in i.message for i in hard), (
        f"HARD_BLOCK message must explain the env was non-absolute: "
        f"{[i.message for i in hard]}"
    )
