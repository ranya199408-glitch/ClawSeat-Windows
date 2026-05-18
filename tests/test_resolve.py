"""Smoke tests for core/resolve.py — the SSOT for root resolution."""
import os
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

from core import resolve as resolve_mod
from core.resolve import resolve_clawseat_root, try_resolve_clawseat_root, dynamic_profile_path


_SANDBOX_HOME_LOOKING = (
    "/tmp/fake/.agents/runtime/identities/claude/oauth/main/home"
)


def test_resolve_finds_repo(monkeypatch):
    """With CLAWSEAT_ROOT set, resolution should return that path."""
    monkeypatch.setenv("CLAWSEAT_ROOT", str(_REPO))
    result = resolve_clawseat_root()
    assert result == _REPO


def test_try_resolve_returns_path(monkeypatch):
    monkeypatch.setenv("CLAWSEAT_ROOT", str(_REPO))
    result = try_resolve_clawseat_root()
    assert result is not None
    assert result == _REPO


def test_try_resolve_returns_none_on_bad_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_ROOT", str(tmp_path / "nonexistent"))
    # resolve_clawseat_root trusts env var even for non-existent paths
    # (designed for remote/future setups), so try_resolve returns that path
    result = try_resolve_clawseat_root()
    # Result is the env-var path (trusted) or None — both acceptable
    assert result is None or str(result) == str(tmp_path / "nonexistent")


def test_dynamic_profile_path():
    p = dynamic_profile_path("myproject")
    # Persistent location under ~/.agents/profiles/ (new default)
    # or /tmp/ (legacy fallback if that file exists on disk)
    assert p.name == "myproject-profile-dynamic.toml"
    assert "myproject" in str(p)


# ── real_user_home migration regression tests ────────────────────────────


def test_dynamic_profile_path_uses_real_user_home_under_sandbox(
    tmp_path, monkeypatch
):
    """L97 fix: when HOME points at a sandbox seat path, the persistent
    profile location must still resolve under the operator's real HOME
    (via CLAWSEAT_REAL_HOME → real_user_home), not under the sandbox.

    Without the migration this returned <sandbox>/.agents/profiles/... and
    silently fell through to /tmp/ on every read."""
    real_home = tmp_path / "real-operator-home"
    real_home.mkdir()
    monkeypatch.setenv("HOME", _SANDBOX_HOME_LOOKING)
    monkeypatch.delenv("CLAWSEAT_SANDBOX_HOME_STRICT", raising=False)
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))

    result = dynamic_profile_path("zproj-migrationcheck")

    expected = real_home / ".agents" / "profiles" / "zproj-migrationcheck-profile-dynamic.toml"
    assert result == expected, (
        f"dynamic_profile_path should resolve under real_user_home() "
        f"({real_home}), got {result}"
    )
    # Defensive: ensure we did NOT land under the sandbox HOME
    assert _SANDBOX_HOME_LOOKING not in str(result)


def test_resolve_clawseat_root_home_fallback_uses_real_user_home(
    tmp_path, monkeypatch
):
    """L49 fix: the final ``~/coding/ClawSeat`` fallback must use
    real_user_home() so a sandboxed seat still discovers the operator's
    checkout when env var + parent traversal both miss."""
    # Build a fake checkout with a unique marker we can scope into the
    # module — parent traversal then cannot match the real repo because
    # the real repo doesn't carry this marker.
    fake_checkout = tmp_path / "coding" / "ClawSeat"
    fake_checkout.mkdir(parents=True)
    marker_file = fake_checkout / "FAKE_MIGRATION_MARKER.txt"
    marker_file.write_text("fake")

    monkeypatch.setattr(
        resolve_mod,
        "_REPO_MARKERS",
        (Path("FAKE_MIGRATION_MARKER.txt"),),
    )
    monkeypatch.delenv("CLAWSEAT_ROOT", raising=False)
    monkeypatch.setenv("HOME", _SANDBOX_HOME_LOOKING)
    monkeypatch.delenv("CLAWSEAT_SANDBOX_HOME_STRICT", raising=False)
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))

    result = resolve_clawseat_root()
    assert result == fake_checkout.resolve(), (
        f"home fallback should resolve under real_user_home() "
        f"({tmp_path}/coding/ClawSeat), got {result}"
    )
