"""Audit finding #6 — shared skill-level secrets injection.

ClawSeat's secret_file is auth-tied (auth_mode=api/oauth_token only).
Skills like cartooner-image / cartooner-audio need provider keys
(MINIMAX_API_KEY, etc.) regardless of auth mode. Without the shared-
secrets path, builder-image (codex/oauth) couldn't read MINIMAX_API_KEY
and was forced to source the cartooner repo's .env (sandbox isolation
breach).

Convention: ~/.agents/secrets/shared/*.env files are sourced into every
seat's sandbox env regardless of auth mode.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_agent_admin_session_isolation_helpers", _HELPERS_PATH
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

aas = _HELPERS.aas


def _make_resolver_session(tmp_path: Path, **overrides):
    """Minimal session for resolver test (codex/oauth/openai)."""
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    base = dict(
        engineer_id="builder-image",
        project="demo",
        tool="codex",
        auth_mode="oauth",
        provider="openai",
        runtime_dir=str(runtime_dir),
        workspace=str(workspace),
        bin_path="/opt/homebrew/bin/codex",
        secret_file="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_resolver(tmp_path: Path):
    from agent_admin_resolve import ResolveHandlers
    hooks = MagicMock()
    hooks.common_env.return_value = {}
    hooks.ensure_dir = lambda p: p.mkdir(parents=True, exist_ok=True)
    hooks.parse_env_file = lambda p: {
        line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip().strip('"').strip("'")
        for line in p.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.strip().startswith("#")
    }
    hooks.error_cls = RuntimeError
    hooks.sessions_root = tmp_path / "sessions"
    return ResolveHandlers(hooks)


def test_shared_secrets_dir_injected_for_codex_oauth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Codex+oauth seat (no secret_file) gets MINIMAX_API_KEY from shared/."""
    fake_home = tmp_path / "home"
    shared_dir = fake_home / ".agents" / "secrets" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "minimax.env").write_text("MINIMAX_API_KEY=<MINIMAX_API_KEY>\n", encoding="utf-8")

    monkeypatch.setenv("AGENT_HOME", str(fake_home))
    monkeypatch.delenv("CLAWSEAT_SHARED_SECRETS_DIR", raising=False)

    resolver = _make_resolver(tmp_path)
    session = _make_resolver_session(tmp_path)
    _binary, env = resolver.build_runtime(session)
    assert env.get("MINIMAX_API_KEY") == "test-mm-key-XYZ"


def test_shared_secrets_multi_file_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Multiple .env files under shared/ all get sourced (sorted order)."""
    fake_home = tmp_path / "home"
    shared_dir = fake_home / ".agents" / "secrets" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "01-minimax.env").write_text("MINIMAX_API_KEY=A\n", encoding="utf-8")
    (shared_dir / "02-elevenlabs.env").write_text("ELEVEN_API_KEY=B\n", encoding="utf-8")

    monkeypatch.setenv("AGENT_HOME", str(fake_home))
    monkeypatch.delenv("CLAWSEAT_SHARED_SECRETS_DIR", raising=False)

    resolver = _make_resolver(tmp_path)
    session = _make_resolver_session(tmp_path)
    _binary, env = resolver.build_runtime(session)
    assert env.get("MINIMAX_API_KEY") == "A"
    assert env.get("ELEVEN_API_KEY") == "B"


def test_auth_tied_secret_wins_over_shared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If auth-tied secret_file already set MINIMAX_API_KEY, shared/ does NOT clobber."""
    fake_home = tmp_path / "home"
    shared_dir = fake_home / ".agents" / "secrets" / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "minimax.env").write_text("MINIMAX_API_KEY=<MINIMAX_API_KEY>\n", encoding="utf-8")

    # Simulate auth-tied env already in place
    monkeypatch.setenv("AGENT_HOME", str(fake_home))
    monkeypatch.delenv("CLAWSEAT_SHARED_SECRETS_DIR", raising=False)

    resolver = _make_resolver(tmp_path)
    # Pretend common_env already has the auth-tied key
    resolver.hooks.common_env.return_value = {"MINIMAX_API_KEY": "auth-tied-value"}
    session = _make_resolver_session(tmp_path)
    _binary, env = resolver.build_runtime(session)
    assert env.get("MINIMAX_API_KEY") == "auth-tied-value"


def test_explicit_shared_secrets_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """CLAWSEAT_SHARED_SECRETS_DIR overrides default location."""
    custom_dir = tmp_path / "elsewhere" / "myshared"
    custom_dir.mkdir(parents=True)
    (custom_dir / "x.env").write_text("MY_KEY=<MY_KEY>\n", encoding="utf-8")

    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGENT_HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_SHARED_SECRETS_DIR", str(custom_dir))

    resolver = _make_resolver(tmp_path)
    session = _make_resolver_session(tmp_path)
    _binary, env = resolver.build_runtime(session)
    assert env.get("MY_KEY") == "via-explicit"


def test_no_shared_dir_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Resolver still works when shared/ doesn't exist."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    # No shared/ dir created
    monkeypatch.setenv("AGENT_HOME", str(fake_home))
    monkeypatch.delenv("CLAWSEAT_SHARED_SECRETS_DIR", raising=False)

    resolver = _make_resolver(tmp_path)
    session = _make_resolver_session(tmp_path)
    _binary, env = resolver.build_runtime(session)
    # Just verify no crash, env is some dict
    assert isinstance(env, dict)
