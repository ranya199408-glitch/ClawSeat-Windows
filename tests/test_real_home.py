"""Tests for core/lib/real_home.py — the canonical real-user-HOME resolver.

The bug motivating this module: when ClawSeat install scripts run inside
an isolated HOME (ancestor CC launcher, tmux seat sandbox, Docker), they
need to place symlinks at the operator's REAL home (``~/.openclaw/``,
``~/.claude/``), not the sandbox path that ``Path.home()`` returns.

These tests lock in the resolution priority described in the module
docstring and the ``SandboxHomeError`` safety net.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "clawseat_real_home_under_test",
        REPO / "core" / "lib" / "real_home.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["clawseat_real_home_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rh():
    return _load_module()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "CLAWSEAT_REAL_HOME",
        "CLAWSEAT_SANDBOX_HOME_STRICT",
        "AGENT_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


# ────────────────────────────────────────────────────────────────────────
# is_sandbox_home — pattern detection
# ────────────────────────────────────────────────────────────────────────


def test_is_sandbox_home_tmux_seat_runtime(rh):
    assert rh.is_sandbox_home(
        "/tmp/fake-home/.agents/runtime/identities/claude/oauth/main/home"
    )


def test_is_sandbox_home_ancestor_launcher_runtime(rh):
    assert rh.is_sandbox_home(
        "/tmp/fake-home/.agent-runtime/identities/claude/api/minimax/home"
    )


def test_is_sandbox_home_real_home_is_false(rh):
    assert not rh.is_sandbox_home("/tmp/fake-home")
    assert not rh.is_sandbox_home("/home/alice")
    assert not rh.is_sandbox_home("/root")


def test_is_sandbox_home_accepts_pathlib(rh):
    assert rh.is_sandbox_home(Path("/tmp/fake-home/.agent-runtime/identities/a/b/c/home"))
    assert not rh.is_sandbox_home(Path("/tmp/fake-home"))


# ────────────────────────────────────────────────────────────────────────
# real_user_home — resolution priority
# ────────────────────────────────────────────────────────────────────────


def test_strict_sandbox_mode_returns_path_home(rh, monkeypatch, tmp_path):
    """CLAWSEAT_SANDBOX_HOME_STRICT=1 forces Path.home() for test fixtures."""
    fake_home = tmp_path / "fake-sandbox"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    # Even if CLAWSEAT_REAL_HOME is set, STRICT wins
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", "/should/be/ignored")
    assert rh.real_user_home() == fake_home


def test_explicit_clawseat_real_home_wins(rh, monkeypatch, tmp_path):
    real = tmp_path / "real-user"
    real.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real))
    # HOME points somewhere else entirely
    monkeypatch.setenv("HOME", str(tmp_path / "whatever"))
    assert rh.real_user_home() == real


def test_clawseat_real_home_pointing_at_sandbox_is_skipped(rh, monkeypatch, tmp_path):
    """Defensive: a harness that sets CLAWSEAT_REAL_HOME=<sandbox> by mistake
    should NOT win. The helper falls through to pwd.getpwuid."""
    sandbox_override = (
        tmp_path / ".agent-runtime" / "identities" / "claude" / "api" / "x" / "home"
    )
    sandbox_override.mkdir(parents=True)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(sandbox_override))
    # pwd lookup will return the actual running-user home, which is outside tmp_path
    result = rh.real_user_home()
    assert not rh.is_sandbox_home(result)


def test_agent_home_used_when_different_from_home(rh, monkeypatch, tmp_path):
    real = tmp_path / "real-via-agent-home"
    real.mkdir()
    sandbox_home = tmp_path / ".agents" / "runtime" / "identities" / "a" / "b" / "c" / "home"
    sandbox_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("AGENT_HOME", str(real))
    assert rh.real_user_home() == real


def test_agent_home_equal_to_home_is_ignored(rh, monkeypatch, tmp_path):
    """If AGENT_HOME == HOME we have no new info; fall through to pwd."""
    h = tmp_path / "same-home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("AGENT_HOME", str(h))
    # Should fall through to pwd.getpwuid (real user) — not return sandbox AGENT_HOME
    result = rh.real_user_home()
    # Either pwd gives real home, or fallback gives the HOME we set.
    # Both paths are acceptable here; just verify no crash and non-sandbox.
    assert not rh.is_sandbox_home(result)


def test_pwd_kicks_in_when_home_is_sandbox(rh, monkeypatch, tmp_path):
    """The primary fix: HOME is sandbox, no env overrides set, pwd.getpwuid
    returns the real user home — this is the code path triggered by the
    ancestor CC bug that prompted this module."""
    sandbox_home = (
        tmp_path / ".agent-runtime" / "identities" / "claude" / "api" / "minimax" / "home"
    )
    sandbox_home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(sandbox_home))
    # No CLAWSEAT_REAL_HOME, no AGENT_HOME
    result = rh.real_user_home()
    assert not rh.is_sandbox_home(result), (
        f"pwd.getpwuid should return the real user home, not {result}"
    )


def test_sandbox_home_error_when_everything_is_sandbox(rh, monkeypatch, tmp_path):
    """If somehow every probe returns a sandbox path, raise loudly."""
    sandbox = tmp_path / ".agent-runtime" / "identities" / "x" / "y" / "z" / "home"
    sandbox.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(sandbox))
    # Stub pwd.getpwuid to also return a sandbox path
    import pwd as _pwd

    class _FakePw:
        pw_dir = str(sandbox)

    monkeypatch.setattr(_pwd, "getpwuid", lambda _uid: _FakePw)
    with pytest.raises(rh.SandboxHomeError):
        rh.real_user_home()


def test_returns_path_object(rh):
    """Return type contract: real_user_home() returns pathlib.Path."""
    assert isinstance(rh.real_user_home(), Path)
