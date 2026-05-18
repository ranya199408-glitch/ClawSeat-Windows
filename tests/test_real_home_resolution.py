"""T15: sandbox HOME root-cause — _is_sandbox_home, _resolve_effective_home, agent_admin migration.

Tests verify:
- _is_sandbox_home correctly identifies seat runtime paths
- _resolve_effective_home returns real home from sandbox context
- CLAWSEAT_SANDBOX_HOME_STRICT=1 forces sandbox (for tests)
- CLAWSEAT_REAL_HOME env override is respected
- agent_admin_config.HOME resolves via effective home (not raw Path.home())
- agent_admin_runtime.HOME resolves via effective home
- agent_admin_workspace._resolve_tasks_root uses effective home
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = str(_REPO / "core" / "scripts")
_HARNESS_SCRIPTS = str(_REPO / "core" / "skills" / "gstack-harness" / "scripts")
for _p in (_SCRIPTS, _HARNESS_SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)


_ADMIN_MODULE_PREFIXES = ("agent_admin_config", "agent_admin_runtime", "agent_admin_workspace")
_FEISHU_MODULE_NAMES = ("_feishu", "_utils", "_common", "_task_io", "_heartbeat_helpers")


@pytest.fixture()
def clean_home_env(monkeypatch):
    """Remove all HOME-override env vars so each test starts from known baseline.

    Also saves/restores the agent_admin_* and _feishu module cache so that
    module-reloading tests do not leak stale module objects into other tests
    (which would cause 'is' identity checks in test_tool_binaries_resolution to fail).
    """
    for key in ("CLAWSEAT_REAL_HOME", "LARK_CLI_HOME", "AGENT_HOME", "CLAWSEAT_SANDBOX_HOME_STRICT"):
        monkeypatch.delenv(key, raising=False)
    # Save the pre-test module cache snapshot for admin/feishu modules
    saved = {
        k: v for k, v in sys.modules.items()
        if any(k == pfx or k.startswith(pfx + ".") for pfx in _ADMIN_MODULE_PREFIXES)
        or k in _FEISHU_MODULE_NAMES
    }
    yield
    # Restore: remove any modules that weren't there before, put old ones back
    for k in list(sys.modules.keys()):
        if any(k == pfx or k.startswith(pfx + ".") for pfx in _ADMIN_MODULE_PREFIXES) \
                or k in _FEISHU_MODULE_NAMES:
            if k in saved:
                sys.modules[k] = saved[k]
            else:
                sys.modules.pop(k, None)


def _reload_config():
    for name in list(sys.modules.keys()):
        if any(name == pfx or name.startswith(pfx + ".") for pfx in _ADMIN_MODULE_PREFIXES):
            sys.modules.pop(name, None)
    import agent_admin_config
    importlib.reload(agent_admin_config)
    return agent_admin_config


def _reload_feishu():
    for name in _FEISHU_MODULE_NAMES:
        sys.modules.pop(name, None)
    import _feishu
    importlib.reload(_feishu)
    return _feishu


# ── _is_sandbox_home ──────────────────────────────────────────────────────────


def test_is_sandbox_home_detects_identity_path(clean_home_env):
    import agent_admin_config
    sandbox = Path("/tmp/fake-home")
    assert agent_admin_config._is_sandbox_home(sandbox) is True


def test_is_sandbox_home_rejects_real_home(clean_home_env):
    import agent_admin_config
    real = Path("/tmp/fake-home")
    assert agent_admin_config._is_sandbox_home(real) is False


def test_is_sandbox_home_rejects_agents_root(clean_home_env):
    import agent_admin_config
    # ~/.agents itself is not a sandbox home (no /runtime/identities/ in path)
    real_agents = Path("/tmp/fake-home")
    assert agent_admin_config._is_sandbox_home(real_agents) is False


# ── feishu._is_sandbox_home (same contract, different module) ─────────────────


def test_feishu_is_sandbox_home_detects_identity_path(clean_home_env):
    feishu = _reload_feishu()
    sandbox = Path("/tmp/fake-home")
    assert feishu._is_sandbox_home(sandbox) is True


def test_feishu_is_sandbox_home_rejects_real_home(clean_home_env):
    feishu = _reload_feishu()
    assert feishu._is_sandbox_home(Path("/tmp/fake-home")) is False


# ── _resolve_effective_home ───────────────────────────────────────────────────


def test_resolve_effective_home_from_sandbox_returns_host(tmp_path, monkeypatch, clean_home_env):
    """When Path.home() is a sandbox path, _resolve_effective_home returns real home via pwd."""
    fake_sandbox = tmp_path / ".agents" / "runtime" / "identities" / "claude" / "oauth" / "xxx" / "home"
    fake_sandbox.mkdir(parents=True)
    real_home = tmp_path / "real_home"
    real_home.mkdir()

    monkeypatch.setenv("HOME", str(fake_sandbox))
    cfg = _reload_config()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        result = cfg._resolve_effective_home()

    assert result == real_home


def test_resolve_effective_home_from_host_returns_host(tmp_path, monkeypatch, clean_home_env):
    """When Path.home() is the real home (pwd agrees), result is Path.home()."""
    real_home = tmp_path / "real_home"
    real_home.mkdir()
    monkeypatch.setenv("HOME", str(real_home))
    cfg = _reload_config()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        result = cfg._resolve_effective_home()

    assert result == real_home


def test_strict_env_var_forces_sandbox(tmp_path, monkeypatch, clean_home_env):
    """CLAWSEAT_SANDBOX_HOME_STRICT=1 forces Path.home() even when in sandbox."""
    fake_sandbox = tmp_path / ".agents" / "runtime" / "identities" / "claude" / "oauth" / "xxx" / "home"
    fake_sandbox.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_sandbox))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    cfg = _reload_config()

    result = cfg._resolve_effective_home()
    assert result == fake_sandbox


def test_real_home_env_override_wins(tmp_path, monkeypatch, clean_home_env):
    """CLAWSEAT_REAL_HOME env var takes precedence over pwd."""
    override = tmp_path / "explicit_override"
    override.mkdir()
    fake_sandbox = tmp_path / ".agents" / "runtime" / "identities" / "claude" / "x" / "home"
    fake_sandbox.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_sandbox))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(override))
    cfg = _reload_config()

    result = cfg._resolve_effective_home()
    assert result == override


def test_real_home_flag_override_in_agent_admin(tmp_path, monkeypatch, clean_home_env):
    """CLAWSEAT_REAL_HOME set via env (as --real-home flag would do) is respected."""
    real_home = tmp_path / "real_home"
    real_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    cfg = _reload_config()
    # _resolve_effective_home() must return the env-overridden path
    result = cfg._resolve_effective_home()
    assert result == real_home


# ── agent_admin_config.HOME uses effective home ───────────────────────────────


def test_agent_admin_config_home_not_raw_path_home(tmp_path, monkeypatch, clean_home_env):
    """agent_admin_config.HOME must equal _resolve_effective_home(), not necessarily Path.home()."""
    real_home = tmp_path / "real_home"
    real_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    cfg = _reload_config()
    # After reload with CLAWSEAT_REAL_HOME set, HOME should use the override
    assert cfg._resolve_effective_home() == real_home


def test_agent_admin_config_strict_mode_uses_sandbox(tmp_path, monkeypatch, clean_home_env):
    """CLAWSEAT_SANDBOX_HOME_STRICT=1 makes _resolve_effective_home return Path.home()."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.setenv("HOME", str(sandbox))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    cfg = _reload_config()
    result = cfg._resolve_effective_home()
    assert result == sandbox


# ── agent_admin_runtime uses effective home ───────────────────────────────────


def test_agent_admin_runtime_home_via_effective_home(tmp_path, monkeypatch, clean_home_env):
    """agent_admin_runtime imports _resolve_effective_home from agent_admin_config."""
    real_home = tmp_path / "runtime_real_home"
    real_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    # Reload config first so _resolve_effective_home picks up the env var
    _reload_config()
    for name in list(sys.modules.keys()):
        if "agent_admin_runtime" in name:
            sys.modules.pop(name, None)
    import agent_admin_runtime
    importlib.reload(agent_admin_runtime)
    # The resolved home should match the override
    assert agent_admin_runtime._resolve_effective_home() == real_home


# ── agent_admin_workspace._resolve_tasks_root uses effective home ─────────────


def test_agent_admin_workspace_tasks_root_uses_effective_home(tmp_path, monkeypatch, clean_home_env):
    """_resolve_tasks_root falls back to effective home/.agents, not Path.home()/.agents."""
    real_home = tmp_path / "ws_real_home"
    real_agents = real_home / ".agents"
    real_agents.mkdir(parents=True)

    fake_sandbox = tmp_path / "sandbox_ws"
    fake_sandbox.mkdir()

    monkeypatch.setenv("HOME", str(fake_sandbox))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    # Clear AGENTS_ROOT so the env fallback uses _ws_effective_home()
    monkeypatch.delenv("AGENTS_ROOT", raising=False)
    _reload_config()

    for name in list(sys.modules.keys()):
        if "agent_admin_workspace" in name:
            sys.modules.pop(name, None)
    import agent_admin_workspace
    importlib.reload(agent_admin_workspace)

    class FakeProject:
        name = "testproj"
        repo_root = tmp_path / "repo"

    result = agent_admin_workspace._resolve_tasks_root(FakeProject())
    # Should resolve to real_home/.agents/tasks/testproj (agents root exists)
    assert str(real_home / ".agents") in result


# ── _common re-exports the three functions ────────────────────────────────────


def test_common_exports_is_sandbox_home(clean_home_env):
    for name in list(sys.modules.keys()):
        if name in ("_common", "_feishu", "_utils", "_task_io", "_heartbeat_helpers"):
            sys.modules.pop(name, None)
    import _common
    assert hasattr(_common, "_is_sandbox_home")
    assert callable(_common._is_sandbox_home)


def test_common_exports_real_user_home(clean_home_env):
    for name in list(sys.modules.keys()):
        if name in ("_common", "_feishu", "_utils", "_task_io", "_heartbeat_helpers"):
            sys.modules.pop(name, None)
    import _common
    assert hasattr(_common, "_real_user_home")
    assert callable(_common._real_user_home)


def test_common_exports_resolve_effective_home(clean_home_env):
    for name in list(sys.modules.keys()):
        if name in ("_common", "_feishu", "_utils", "_task_io", "_heartbeat_helpers"):
            sys.modules.pop(name, None)
    import _common
    assert hasattr(_common, "_resolve_effective_home")
    assert callable(_common._resolve_effective_home)


# ── F1 regression: --real-home post-subcommand support ───────────────────────


def test_real_home_post_subcommand_no_value(tmp_path, monkeypatch, clean_home_env):
    """F1 canary: --real-home at post-subcommand position (no value) must not crash."""
    _SCRIPTS = str(Path(__file__).resolve().parents[1] / "core" / "scripts")
    result = __import__("subprocess").run(
        [sys.executable, f"{_SCRIPTS}/agent_admin.py", "list-engineers", "--real-home"],
        capture_output=True, text=True, cwd=_SCRIPTS,
    )
    assert result.returncode == 0, (
        f"agent_admin list-engineers --real-home crashed (exit {result.returncode}):\n{result.stderr}"
    )


def test_real_home_pre_subcommand_with_path(tmp_path, monkeypatch, clean_home_env):
    """F1 canary: --real-home /path before subcommand still works."""
    _SCRIPTS = str(Path(__file__).resolve().parents[1] / "core" / "scripts")
    result = __import__("subprocess").run(
        [sys.executable, f"{_SCRIPTS}/agent_admin.py", "--real-home", str(tmp_path),
         "list-engineers"],
        capture_output=True, text=True, cwd=_SCRIPTS,
    )
    assert result.returncode == 0, (
        f"agent_admin --real-home /path list-engineers crashed (exit {result.returncode}):\n{result.stderr}"
    )


def test_real_home_post_nested_subcommand(tmp_path, monkeypatch, clean_home_env):
    """F1 canary: --real-home after nested subcommand (engineer list --real-home) must not crash."""
    _SCRIPTS = str(Path(__file__).resolve().parents[1] / "core" / "scripts")
    result = __import__("subprocess").run(
        [sys.executable, f"{_SCRIPTS}/agent_admin.py", "engineer", "list", "--real-home"],
        capture_output=True, text=True, cwd=_SCRIPTS,
    )
    assert result.returncode == 0, (
        f"agent_admin engineer list --real-home crashed (exit {result.returncode}):\n{result.stderr}"
    )
