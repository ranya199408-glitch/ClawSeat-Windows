"""Tests for seat_resolver.py suffix alias fallback (section 2.5).

Root cause: dynamic_roster generates runtime_seats with -N suffixes
(e.g. "builder-1") but dispatch callers use bare names ("builder").
Bare name fails exact-match → file-only → notified_at:null.

Section 2.5 tries target+"-1" through target+"-9" and resolves the
first match to kind=tmux, transparently fixing all dispatch paths.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LIB = _REPO / "core" / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from seat_resolver import SeatResolution, resolve_seat  # noqa: E402


# ── shared helpers ────────────────────────────────────────────────────────────

def _resolve(
    target: str,
    runtime_seats: list[str],
    *,
    declared_seats: list[str] | None = None,
    tmp_path: Path | None = None,
    oc_home: Path | None = None,
) -> SeatResolution:
    """Thin wrapper: no real session.toml or openclaw workspace."""
    handoff_dir = (tmp_path or Path("/tmp")) / "handoffs"
    return resolve_seat(
        target=target,
        profile_seats=declared_seats or runtime_seats,
        profile_project_name="testproject",
        profile_handoff_dir=handoff_dir,
        profile_session_name_resolver=lambda proj, seat: f"{proj}-{seat}-claude",
        profile_runtime_seats=runtime_seats,
        _openclaw_home=oc_home or Path("/nonexistent-oc-home"),
    )


# ── Test 1: alias builder → builder-1 ───────────────────────────────────────


def test_alias_builder_to_builder_1() -> None:
    """Bare 'builder' resolves to tmux when 'builder-1' is in runtime_seats."""
    result = _resolve("builder", ["builder-1", "reviewer-1", "planner"])
    assert result.kind == "tmux", f"expected tmux, got {result.kind!r}"
    assert result.session_name == "testproject-builder-1-claude"


# ── Test 2: alias not found falls to file-only ───────────────────────────────


def test_alias_not_found_falls_to_file_only() -> None:
    """When no 'builder-*' seat exists, resolution falls through to file-only."""
    result = _resolve("builder", ["planner"])
    assert result.kind == "file-only", f"expected file-only, got {result.kind!r}"


# ── Test 3: exact match not broken by alias logic ────────────────────────────


def test_exact_match_not_broken_by_alias() -> None:
    """When 'builder' (no suffix) IS in runtime_seats, exact match wins immediately."""
    result = _resolve("builder", ["builder", "planner"])
    assert result.kind == "tmux", f"expected tmux, got {result.kind!r}"
    # Exact match resolves to 'builder', not 'builder-1'
    assert result.session_name == "testproject-builder-claude"


# ── Test 4: multiple suffixes — first match wins ──────────────────────────────


def test_multiple_suffix_resolve_to_first() -> None:
    """When builder-1, -2, -3 all exist, resolves to builder-1 (first)."""
    result = _resolve("builder", ["builder-1", "builder-2", "builder-3"])
    assert result.kind == "tmux"
    assert result.session_name == "testproject-builder-1-claude"


# ── Test 5: alias emits note to stderr ───────────────────────────────────────


def test_alias_emits_note_to_stderr(capsys: pytest.CaptureFixture) -> None:
    """Alias resolution must emit a diagnostic note to stderr."""
    result = _resolve("reviewer", ["reviewer-1", "planner"])
    assert result.kind == "tmux"
    captured = capsys.readouterr()
    assert "alias" in captured.err.lower(), (
        f"expected 'alias' note in stderr; got:\n{captured.err!r}"
    )
    assert "reviewer" in captured.err
    assert "reviewer-1" in captured.err


# ── Test 6: workspace contract does not interfere with alias ─────────────────


def test_workspace_contract_not_affected(tmp_path: Path) -> None:
    """An OpenClaw workspace-<target> contract must NOT be reached when alias resolves first."""
    # Create a workspace-builder contract that would be checked in step 3
    oc_home = tmp_path / ".openclaw"
    contract_dir = oc_home / "workspace-builder"
    contract_dir.mkdir(parents=True)
    (contract_dir / "WORKSPACE_CONTRACT.toml").write_text(
        'feishu_group_id = "<FEISHU_GROUP_ID>"\nseat_id = "builder"\nproject = "testproject"\n',
        encoding="utf-8",
    )
    # builder-1 in runtime_seats → alias resolves first; openclaw is NOT reached
    result = _resolve("builder", ["builder-1", "planner"], tmp_path=tmp_path, oc_home=oc_home)
    assert result.kind == "tmux", (
        f"alias should resolve before openclaw workspace; got kind={result.kind!r}"
    )
    assert result.session_name == "testproject-builder-1-claude"


# ── Reviewer nit pins ────────────────────────────────────────────────────────


def test_alias_session_name_none_when_no_session_toml(tmp_path: Path) -> None:
    """Alias resolution returns kind=tmux with session_name=None when no session.toml
    exists for the aliased seat.  Downstream callers handle None gracefully per
    SeatResolution.__post_init__ contract."""
    # Resolver returns None (no session.toml written) but alias match is valid.
    result = resolve_seat(
        target="builder",
        profile_seats=["builder-1"],
        profile_project_name="testproject",
        profile_handoff_dir=tmp_path / "handoffs",
        # Always-None resolver simulates missing session.toml
        profile_session_name_resolver=lambda proj, seat: None,
        profile_runtime_seats=["builder-1"],
        _openclaw_home=Path("/nonexistent"),
    )
    assert result.kind == "tmux"
    assert result.session_name is None


def test_strict_mode_with_alias_does_not_raise(tmp_path: Path) -> None:
    """strict=True must NOT raise when an alias resolves the seat — alias is a valid
    resolution, not a failure.  Only unresolvable targets should raise in strict mode."""
    result = resolve_seat(
        target="reviewer",
        profile_seats=["reviewer-1"],
        profile_project_name="testproject",
        profile_handoff_dir=tmp_path / "handoffs",
        profile_session_name_resolver=lambda proj, seat: f"{proj}-{seat}-claude",
        profile_runtime_seats=["reviewer-1"],
        strict=True,
        _openclaw_home=Path("/nonexistent"),
    )
    assert result.kind == "tmux"
    assert result.session_name == "testproject-reviewer-1-claude"


# ── Integration: real install profile end-to-end ─────────────────────────────


def test_install_profile_builder_resolves_tmux() -> None:
    """With the real install profile, 'builder' must resolve to kind=tmux (not file-only).
    This is the end-to-end symptom fix: notified_at was null because target_kind was file-only.
    """
    _SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    from _common import load_profile
    from seat_resolver import resolve_seat_from_profile

    profile_path = _REPO.parents[0] / ".agents" / "profiles" / "install-profile-dynamic.toml"
    if not profile_path.exists():
        pytest.skip(f"install profile not found at {profile_path}")

    profile = load_profile(str(profile_path))
    result = resolve_seat_from_profile("builder", profile)
    assert result.kind == "tmux", (
        f"'builder' should now resolve to kind=tmux on install profile; "
        f"got kind={result.kind!r}. "
        f"runtime_seats: {getattr(profile, 'runtime_seats', 'n/a')}"
    )
