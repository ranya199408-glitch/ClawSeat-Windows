"""T15: verify _real_user_home() behavior is consistent across implementations.

memory-oracle has its own copies of _real_user_home in _memory_paths.py,
memory_deliver.py, and scan_environment.py. This test locks the behavioral
contract so future dedup (PR-2) preserves correctness.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HARNESS = str(_REPO / "core" / "skills" / "gstack-harness" / "scripts")
_MEMORY_ORACLE = str(_REPO / "core" / "skills" / "memory-oracle" / "scripts")
for _p in (_HARNESS, _MEMORY_ORACLE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture()
def clean_home_env(monkeypatch):
    for key in ("CLAWSEAT_REAL_HOME", "LARK_CLI_HOME", "AGENT_HOME", "CLAWSEAT_SANDBOX_HOME_STRICT"):
        monkeypatch.delenv(key, raising=False)
    yield


def _import_feishu_fresh():
    for name in ("_feishu", "_utils"):
        sys.modules.pop(name, None)
    import importlib
    import _feishu
    importlib.reload(_feishu)
    return _feishu


def _import_memory_paths_fresh():
    for name in list(sys.modules.keys()):
        if "_memory_paths" in name:
            sys.modules.pop(name, None)
    import importlib
    import _memory_paths
    importlib.reload(_memory_paths)
    return _memory_paths


def test_feishu_and_memory_paths_agree_on_real_home(tmp_path, monkeypatch, clean_home_env):
    """Both implementations must return the same path for the same env/pwd state."""
    real_home = tmp_path / "shared_real_home"
    real_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))

    feishu = _import_feishu_fresh()
    feishu_result = feishu._real_user_home()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        mem_paths = _import_memory_paths_fresh()
        mem_result = mem_paths._real_user_home()

    assert feishu_result == real_home, f"feishu._real_user_home() returned {feishu_result}"
    assert mem_result == real_home, f"_memory_paths._real_user_home() returned {mem_result}"


def test_memory_paths_pwd_beats_env_home(tmp_path, monkeypatch, clean_home_env):
    """_memory_paths._real_user_home must use pwd (not HOME env) as primary."""
    fake_sandbox = tmp_path / "sandbox"
    fake_sandbox.mkdir()
    real_home = tmp_path / "real"
    real_home.mkdir()

    monkeypatch.setenv("HOME", str(fake_sandbox))
    mem_paths = _import_memory_paths_fresh()

    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(real_home))
        result = mem_paths._real_user_home()

    assert result == real_home, (
        f"_memory_paths._real_user_home should use pwd, got {result}"
    )
