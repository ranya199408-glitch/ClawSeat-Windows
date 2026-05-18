"""Lock the sandbox-HOME resolution contract for resolve_primary_feishu_group_id.

Background incident
-------------------
During Phase 7 task chain validation, planner (which runs inside a seat
sandbox HOME at ~/.agents/runtime/identities/.../home/) called
`complete_handoff.py --source planner --target koder --frontstage-disposition AUTO_ADVANCE ...`.
The complete_handoff flow branches:

  if openclaw_koder:
      send via Feishu (OC_DELEGATION_REPORT_V1)
  else:
      notify(profile, "koder", message)  # tmux send-keys to 'install-koder-claude'
      require_success(result, "completion notify")

where

  openclaw_koder = planner_to_frontstage and bool(resolve_primary_feishu_group_id(project=...))

In OpenClaw mode, koder is an OpenClaw agent (NOT a tmux seat), so the
tmux notify path hard-fails. Feishu is the only valid channel.

But planner's sandbox HOME has `.lark-cli/config.json` (seeded/inherited
at identity materialization time) and lacks `.openclaw/openclaw.json` (a
real-home-only artifact). The old `_real_user_home` used `.lark-cli/config.json`
as a canary, falsely concluding "this IS the real home" and returning
the sandbox HOME. Then `resolve_primary_feishu_group_id` looked for
WORKSPACE_CONTRACT.toml under that fake real home, found nothing, and
returned None → `openclaw_koder = False` → planner routed through tmux
→ hard-fail with no koder tmux session.

What this test locks
--------------------
1. pwd.getpwuid takes priority over any HOME canary. Even when a sandbox
   HOME looks "lived-in" (has .lark-cli/config.json, or any other user-level
   artifact), the resolver must still return the pwd-authoritative home.
2. Explicit env override (CLAWSEAT_REAL_HOME, LARK_CLI_HOME) still wins
   over pwd — the harness / installer may have more context.
3. resolve_primary_feishu_group_id, when called from within a sandbox HOME,
   must still find the project's feishu_group_id via the real home's
   workspace-koder WORKSPACE_CONTRACT.toml.

This test is defence-in-depth: if anyone "fixes" _real_user_home to
re-introduce a canary shortcut, or drops pwd from the resolution, this
breaks. The failure mode is silent tmux-routing for a seat that shouldn't
use tmux — which is exactly the Phase 7 failure this regression is
about.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))


@pytest.fixture()
def clean_env(monkeypatch):
    """Clean all relevant env vars so each test starts from a known baseline."""
    for key in ("CLAWSEAT_REAL_HOME", "LARK_CLI_HOME", "AGENT_HOME"):
        monkeypatch.delenv(key, raising=False)
    yield


def _reload_feishu():
    """Re-import _feishu so module-level constants (AGENT_HOME) pick up the
    current env. Each test that tweaks AGENT_HOME must call this.
    """
    for name in ("_feishu", "_utils"):
        sys.modules.pop(name, None)
    import importlib
    import _feishu  # noqa: F401 — side-effect import
    importlib.reload(_feishu)
    return _feishu


# ── Core invariant: pwd takes priority over canary ────────────────────────


def test_pwd_beats_lark_cli_canary_in_sandbox(tmp_path, monkeypatch, clean_env):
    """The original bug: sandbox HOME has .lark-cli/config.json (stale seed),
    the canary would falsely return that sandbox path. pwd must beat it.
    """
    # Build a fake sandbox home with a .lark-cli/config.json inside.
    fake_sandbox = tmp_path / "fake_sandbox_home"
    (fake_sandbox / ".lark-cli").mkdir(parents=True)
    (fake_sandbox / ".lark-cli" / "config.json").write_text("{}")

    monkeypatch.setenv("HOME", str(fake_sandbox))
    # pwd should still report the real user home — mock it to a known value.
    real_home = tmp_path / "fake_real_home"
    real_home.mkdir()

    feishu = _reload_feishu()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        result = feishu._real_user_home()

    assert result == real_home, (
        "canary at sandbox HOME should NOT have short-circuited pwd lookup. "
        f"Got {result}, expected {real_home} (the pwd-authoritative home)."
    )


def test_explicit_override_beats_pwd(tmp_path, monkeypatch, clean_env):
    """Highest priority: CLAWSEAT_REAL_HOME env override."""
    override_home = tmp_path / "override_home"
    override_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(override_home))

    feishu = _reload_feishu()
    # pwd would normally answer for the test-runner uid; override must win.
    assert feishu._real_user_home() == override_home


def test_lark_cli_home_alias_also_works(tmp_path, monkeypatch, clean_env):
    """LARK_CLI_HOME is accepted as an alias for the override."""
    override_home = tmp_path / "lark_override"
    override_home.mkdir()
    monkeypatch.setenv("LARK_CLI_HOME", str(override_home))

    feishu = _reload_feishu()
    assert feishu._real_user_home() == override_home


# ── Integration: resolve_primary_feishu_group_id from inside sandbox ─────


def test_group_id_resolves_from_sandbox_via_real_home(tmp_path, monkeypatch, clean_env):
    """End-to-end: a sandbox process still finds the project's feishu_group_id
    because _real_user_home bypasses the sandbox HOME.
    """
    fake_sandbox = tmp_path / "sandbox_home"
    (fake_sandbox / ".lark-cli").mkdir(parents=True)
    (fake_sandbox / ".lark-cli" / "config.json").write_text("{}")

    real_home = tmp_path / "real_home"
    # Write a WORKSPACE_CONTRACT.toml under the real home's expected path.
    contract_dir = real_home / ".openclaw" / "workspace-koder"
    contract_dir.mkdir(parents=True)
    contract_path = contract_dir / "WORKSPACE_CONTRACT.toml"
    contract_path.write_text('feishu_group_id = "<FEISHU_GROUP_ID>"\n')

    monkeypatch.setenv("HOME", str(fake_sandbox))

    feishu = _reload_feishu()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        result = feishu.resolve_primary_feishu_group_id(project="install")

    assert result == "<FEISHU_GROUP_ID>", (
        "resolve_primary_feishu_group_id should have found the group via "
        "the real home's workspace-koder contract, not the sandbox home."
    )


def test_group_id_from_clawseat_managed_workspace(tmp_path, monkeypatch, clean_env):
    """Second resolution path: ~/.agents/workspaces/<project>/koder/WORKSPACE_CONTRACT.toml."""
    fake_sandbox = tmp_path / "sandbox"
    fake_sandbox.mkdir()

    real_home = tmp_path / "real"
    contract_dir = real_home / ".agents" / "workspaces" / "demo" / "koder"
    contract_dir.mkdir(parents=True)
    (contract_dir / "WORKSPACE_CONTRACT.toml").write_text(
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
    )

    monkeypatch.setenv("HOME", str(fake_sandbox))
    feishu = _reload_feishu()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        assert feishu.resolve_primary_feishu_group_id(project="demo") == "<FEISHU_GROUP_ID>"


# ── Negative: truly unknown environment returns None gracefully ─────────


def test_unknown_project_returns_none(tmp_path, monkeypatch, clean_env):
    """If neither contract path exists and openclaw.json has no groups,
    return None (not crash).

    Uses CLAWSEAT_REAL_HOME to anchor _utils / _feishu's module-level
    OPENCLAW_CONFIG_PATH at the tmp home. The old test relied on
    monkeypatching $HOME and a lazy pwd mock, but after the sandbox-HOME
    anchor fix (HOME-fallback → real_user_home SSOT), module-level path
    constants are captured at import time via pwd — so $HOME patches
    applied after module load no longer leak through. CLAWSEAT_REAL_HOME
    wins at import time and reliably seals the module to the fixture dir.
    """
    real_home = tmp_path / "empty_real"
    real_home.mkdir()

    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    feishu = _reload_feishu()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        # No contract, no openclaw.json, no group_ids from sessions. None.
        result = feishu.resolve_primary_feishu_group_id(project="does-not-exist")
    assert result is None


# ── The _lark_cli_real_home delegate returns str of same answer ─────────


def test_lark_cli_real_home_delegates_to_real_user_home(tmp_path, monkeypatch, clean_env):
    """Backwards-compat: _lark_cli_real_home() returns str(_real_user_home())."""
    override_home = tmp_path / "lark_delegate"
    override_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(override_home))

    feishu = _reload_feishu()
    assert feishu._lark_cli_real_home() == str(override_home)
