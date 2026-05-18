"""Tests for _resolve_tool_bin / _default_path in agent_admin_config.py (T1 bundle-B).

Covers env-var override, shutil.which precedence, homebrew fallback, bare-name
fallback, platform-aware DEFAULT_PATH, and runtime re-use of config's value.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import agent_admin_config  # noqa: E402


# ── _resolve_tool_bin ────────────────────────────────────────────────────────

def test_resolve_tool_bin_prefers_which(monkeypatch):
    """shutil.which result takes priority over homebrew path."""
    with patch("agent_admin_config.shutil.which", return_value="/custom/bin/codex"):
        result = agent_admin_config._resolve_tool_bin("codex")
    assert result == "/custom/bin/codex"


def test_resolve_tool_bin_homebrew_fallback_when_which_none(monkeypatch):
    """When which returns None but /opt/homebrew/bin/<name> exists, use it."""
    with (
        patch("agent_admin_config.shutil.which", return_value=None),
        patch("agent_admin_config.os.path.exists", return_value=True),
    ):
        result = agent_admin_config._resolve_tool_bin("codex")
    assert result == "/opt/homebrew/bin/codex"


def test_resolve_tool_bin_bare_name_when_both_missing(monkeypatch):
    """When which is None and homebrew path absent, return bare name."""
    with (
        patch("agent_admin_config.shutil.which", return_value=None),
        patch("agent_admin_config.os.path.exists", return_value=False),
    ):
        result = agent_admin_config._resolve_tool_bin("codex")
    assert result == "codex"


# ── _default_path ────────────────────────────────────────────────────────────

def test_default_path_darwin_prepends_homebrew(monkeypatch):
    """On darwin with no env override, path starts with /opt/homebrew/bin:."""
    monkeypatch.delenv("CLAWSEAT_DEFAULT_PATH", raising=False)
    monkeypatch.setattr(agent_admin_config.sys, "platform", "darwin")
    result = agent_admin_config._default_path()
    assert result.startswith("/opt/homebrew/bin:")


def test_default_path_linux_no_homebrew(monkeypatch):
    """On linux with no env override, path starts with /usr/local/bin and has no /opt/homebrew."""
    monkeypatch.delenv("CLAWSEAT_DEFAULT_PATH", raising=False)
    monkeypatch.setattr(agent_admin_config.sys, "platform", "linux")
    result = agent_admin_config._default_path()
    assert result.startswith("/usr/local/bin")
    assert "/opt/homebrew" not in result


def test_default_path_env_override_wins(monkeypatch):
    """CLAWSEAT_DEFAULT_PATH env var is returned as-is."""
    monkeypatch.setenv("CLAWSEAT_DEFAULT_PATH", "/custom:/bin")
    result = agent_admin_config._default_path()
    assert result == "/custom:/bin"


# ── runtime re-use ───────────────────────────────────────────────────────────

def test_runtime_reuses_config_default_path():
    """agent_admin_runtime.DEFAULT_PATH is the same object as agent_admin_config.DEFAULT_PATH."""
    import agent_admin_runtime  # noqa: PLC0415
    assert agent_admin_runtime.DEFAULT_PATH == agent_admin_config.DEFAULT_PATH


# ── source-grep guard ────────────────────────────────────────────────────────

def test_no_hardcoded_homebrew_claude_in_config_dict():
    """TOOL_BINARIES dict in agent_admin_config.py must not contain literal /opt/homebrew paths."""
    import re
    source = (_SCRIPTS / "agent_admin_config.py").read_text(encoding="utf-8")
    # Find TOOL_BINARIES assignment block
    m = re.search(r"TOOL_BINARIES\s*=\s*\{[^}]+\}", source, re.DOTALL)
    assert m is not None, "TOOL_BINARIES not found in agent_admin_config.py"
    block = m.group(0)
    hardcodes = re.findall(r'"/opt/homebrew/bin/(?:claude|codex|gemini)"', block)
    assert hardcodes == [], f"Literal /opt/homebrew paths found in TOOL_BINARIES: {hardcodes}"
