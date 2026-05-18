"""Regression: profile paths (workspace_root, tasks_root, handoff_dir,
heartbeat_receipt, …) must resolve against the operator's real HOME
even when the ancestor/seat is running inside a sandbox HOME.

Live-install incident this test locks
-------------------------------------
P0.5 bootstrap output surfaced
    workspace_sync: memory status=skip reason=host_workspace_not_found
    host=/tmp/fake-home/.agent-runtime/identities/claude/api/minimax-ancestor-cc/<sandbox-home>/workspaces/install/memory
when the expected host was `/tmp/fake-home/.agents/workspaces/install/memory`.

Root cause: `expand_profile_value()` in _common.py called
`Path(...).expanduser()` which resolves `~` via `$HOME`. When the ancestor
is a Claude Code session launched under a sandbox HOME (e.g.
`~/.agent-runtime/identities/.../home/`), `$HOME` is the sandbox and
profile values like `workspace_root = "~/.agents/workspaces/install"`
expand to `<sandbox>/.agents/workspaces/install`. bootstrap's
`_sync_workspaces_host_to_sandbox` then looks there, finds nothing, and
silently skips the workspace sync → seats launch without the expected
skill symlinks → memory can't find scan_environment.py and similar.

The fix is two-layered:
  1. `_utils.AGENT_HOME` / `_utils.OPENCLAW_HOME` defaults now go through
     core/lib/real_home.real_user_home() (pwd-based, env-override-aware).
  2. `_common.expand_profile_value()` manually rewrites leading `~` with
     `_real_user_home()` before calling `.expanduser()`.

This test exercises both so a regression in either layer surfaces.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import mock


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _reload_harness_modules():
    """Fresh-import _utils, _feishu, _common so module-level constants
    re-evaluate against the current env / pwd mocks."""
    for name in ("_common", "_feishu", "_utils"):
        sys.modules.pop(name, None)
    import _common
    importlib.reload(_common)
    return _common


def test_profile_tilde_expands_against_real_home_not_sandbox(tmp_path, monkeypatch):
    """When `$HOME` is a sandbox but pwd/CLAWSEAT_REAL_HOME point at the
    real home, profile `~` paths must land under the real home."""
    real_home = tmp_path / "real_home"
    real_home.mkdir()
    sandbox_home = tmp_path / "sandbox" / ".agent-runtime" / "identities" / "c" / "a" / "id" / "home"
    sandbox_home.mkdir(parents=True)

    # Simulate ancestor-under-sandbox: $HOME == sandbox
    monkeypatch.setenv("HOME", str(sandbox_home))
    # CLAWSEAT_REAL_HOME env wins in real_user_home() before pwd probe
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    # Clear AGENT_HOME so the _utils default path runs through the resolver
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.delenv("OPENCLAW_HOME", raising=False)

    _common = _reload_harness_modules()

    # 1. Literal ~ in a profile value expands against real_home, NOT sandbox
    resolved = _common.expand_profile_value("~/.agents/workspaces/install")
    assert str(resolved) == str(real_home / ".agents" / "workspaces" / "install"), (
        f"~ expanded to {resolved}, expected {real_home}/.agents/workspaces/install; "
        f"sandbox leak check — path must not contain {sandbox_home}"
    )
    assert str(sandbox_home) not in str(resolved)

    # 2. Module-level AGENTS_ROOT / AGENT_HOME anchor on real home too
    assert str(_common.AGENT_HOME) == str(real_home), _common.AGENT_HOME
    assert str(_common.AGENTS_ROOT) == str(real_home / ".agents"), _common.AGENTS_ROOT


def test_profile_placeholder_still_works_after_fix(tmp_path, monkeypatch):
    """The `{CLAWSEAT_ROOT}` / `{AGENTS_ROOT}` placeholder substitution
    must continue to work — the sandbox fix only changes `~` handling."""
    real_home = tmp_path / "real"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))

    _common = _reload_harness_modules()
    resolved = _common.expand_profile_value("{CLAWSEAT_ROOT}/core/scripts")
    assert resolved.name == "scripts"
    assert "{CLAWSEAT_ROOT}" not in str(resolved)


def test_openclaw_home_anchors_on_real_home_under_sandbox(tmp_path, monkeypatch):
    """_utils.OPENCLAW_HOME default must point at the real home's
    `.openclaw/`, not the sandbox's (otherwise OPENCLAW_CONFIG_PATH
    misses openclaw.json and Feishu group discovery fails silently)."""
    real_home = tmp_path / "host"
    real_home.mkdir()
    sandbox_home = tmp_path / "seat" / ".agent-runtime" / "identities" / "claude" / "api" / "id1" / "home"
    sandbox_home.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.delenv("OPENCLAW_HOME", raising=False)

    _common = _reload_harness_modules()
    assert str(_common.OPENCLAW_HOME) == str(real_home / ".openclaw"), _common.OPENCLAW_HOME


def test_bootstrap_agents_home_default_points_at_real_home(tmp_path, monkeypatch):
    """bootstrap_harness._sync_workspaces_host_to_sandbox uses AGENTS_ROOT
    as its default `agents_home`, not `Path.home() / ".agents"`. This
    prevents the session.toml / host workspace lookup from missing when
    bootstrap runs from an ancestor inside a sandbox HOME.
    """
    real_home = tmp_path / "real"
    real_home.mkdir()
    sandbox_home = tmp_path / "sandbox" / ".agent-runtime" / "identities" / "t" / "a" / "id" / "home"
    sandbox_home.mkdir(parents=True)

    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    monkeypatch.delenv("AGENT_HOME", raising=False)

    # Re-import bootstrap_harness with fresh module-level state so its
    # `from _common import AGENTS_ROOT` picks up the patched env.
    for name in ("bootstrap_harness", "_common", "_feishu", "_utils"):
        sys.modules.pop(name, None)
    import bootstrap_harness
    importlib.reload(bootstrap_harness)

    # Its AGENTS_ROOT comes from _common re-export of _utils.AGENTS_ROOT.
    assert str(bootstrap_harness.AGENTS_ROOT) == str(real_home / ".agents"), (
        f"expected AGENTS_ROOT anchored on real home, got {bootstrap_harness.AGENTS_ROOT}"
    )
