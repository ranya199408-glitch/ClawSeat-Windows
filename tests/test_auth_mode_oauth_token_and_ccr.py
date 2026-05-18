"""C5 tests: new auth modes `oauth_token` (long-lived token, no Keychain)
and `ccr` (Claude Code Router local proxy for provider multiplexing)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))

from agent_admin_config import (  # noqa: E402
    ALL_AUTH_MODES,
    AUTH_MODES_REQUIRING_SECRET_FILE,
    AUTH_MODES_WITHOUT_SECRET_FILE,
    DEFAULT_CCR_BASE_URL,
    SUPPORTED_RUNTIME_MATRIX,
    supported_runtime_summary_lines,
    validate_runtime_combo,
)


# ── Matrix: new modes are registered ──────────────────────────────────


def test_matrix_includes_oauth_token_for_claude():
    assert SUPPORTED_RUNTIME_MATRIX["claude"].get("oauth_token") == ("anthropic",)


def test_matrix_includes_ccr_for_claude():
    assert SUPPORTED_RUNTIME_MATRIX["claude"].get("ccr") == ("ccr-local",)


def test_new_modes_rejected_for_codex_and_gemini():
    assert "oauth_token" not in SUPPORTED_RUNTIME_MATRIX["codex"]
    assert "ccr" not in SUPPORTED_RUNTIME_MATRIX["codex"]
    assert "oauth_token" not in SUPPORTED_RUNTIME_MATRIX["gemini"]
    assert "ccr" not in SUPPORTED_RUNTIME_MATRIX["gemini"]


def test_validate_runtime_combo_accepts_new_claude_combos():
    # Should not raise.
    validate_runtime_combo("claude", "oauth_token", "anthropic")
    validate_runtime_combo("claude", "ccr", "ccr-local")


def test_validate_runtime_combo_rejects_new_modes_for_other_tools():
    with pytest.raises(ValueError):
        validate_runtime_combo("codex", "oauth_token", "anthropic")
    with pytest.raises(ValueError):
        validate_runtime_combo("gemini", "ccr", "ccr-local")


def test_summary_mentions_new_modes():
    lines = "\n".join(supported_runtime_summary_lines())
    assert "claude` + `oauth_token`" in lines
    assert "claude` + `ccr`" in lines


def test_auth_mode_families_are_consistent():
    # Sanity: the two families partition ALL_AUTH_MODES.
    assert ALL_AUTH_MODES == AUTH_MODES_REQUIRING_SECRET_FILE | AUTH_MODES_WITHOUT_SECRET_FILE
    assert AUTH_MODES_REQUIRING_SECRET_FILE.isdisjoint(AUTH_MODES_WITHOUT_SECRET_FILE)
    assert "oauth_token" in AUTH_MODES_REQUIRING_SECRET_FILE
    assert "ccr" in AUTH_MODES_WITHOUT_SECRET_FILE


# ── build_runtime: env injection branches ─────────────────────────────


def _make_handlers(tmp_path, secret_env=None):
    """Minimal ResolveHandlers with hooks stubbed for env-build tests."""
    from agent_admin_resolve import ResolveHandlers, ResolveHooks
    hooks = ResolveHooks(
        error_cls=RuntimeError,
        default_tool_args={},
        codex_api_provider_configs={},
        common_env=lambda: {},
        ensure_dir=lambda p: p.mkdir(parents=True, exist_ok=True),
        parse_env_file=lambda path: dict(secret_env or {}),
        write_codex_api_config=lambda *a, **kw: None,
        write_text=lambda p, c, m=None: p.write_text(c),
        load_project=lambda name: SimpleNamespace(repo_root=str(tmp_path)),
        load_projects=lambda: {},
        load_engineers=lambda: {},
        load_sessions=lambda: {},
        get_current_project_name=lambda projects: None,
        display_name_for=lambda eng, fallback: fallback,
    )
    handlers = ResolveHandlers(hooks)
    # sessions_root is referenced in the 'api' error branch — add it as attr
    # so that path compiles if we ever hit that branch.
    handlers.hooks.sessions_root = tmp_path
    return handlers


def _make_session(tmp_path, *, tool="claude", auth_mode="oauth_token",
                  provider="anthropic", secret_file: Path | None = None):
    runtime_dir = tmp_path / "rt"
    runtime_dir.mkdir()
    return SimpleNamespace(
        engineer_id="planner",
        project="install",
        tool=tool,
        auth_mode=auth_mode,
        provider=provider,
        identity="claude.oauth_token.anthropic.install.planner",
        workspace=str(tmp_path),
        runtime_dir=str(runtime_dir),
        session="install-planner-claude",
        bin_path="/usr/bin/claude",
        monitor=True,
        legacy_sessions=[],
        launch_args=[],
        secret_file=str(secret_file) if secret_file else "",
        wrapper="",
    )


# ── oauth_token path ──────────────────────────────────────────────────


def test_oauth_token_injects_claude_env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    secret_file = tmp_path / "oauth.env"
    secret_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>\n")
    handlers = _make_handlers(
        tmp_path, secret_env={"CLAUDE_CODE_OAUTH_TOKEN": "fixture-anthropic-oauth"}
    )
    session = _make_session(tmp_path, secret_file=secret_file)

    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ):
        binary, env = handlers.build_runtime(session)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "fixture-anthropic-oauth"
    # Defensive clearing of ambient anthropic env:
    assert "ANTHROPIC_API_KEY" not in env
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env


def test_oauth_token_rejects_codex(tmp_path):
    secret_file = tmp_path / "oauth.env"
    secret_file.write_text("CLAUDE_CODE_OAUTH_TOKEN=x\n")
    handlers = _make_handlers(tmp_path, secret_env={"CLAUDE_CODE_OAUTH_TOKEN": "x"})
    session = _make_session(
        tmp_path, tool="codex", auth_mode="oauth_token",
        provider="anthropic", secret_file=secret_file,
    )
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ), pytest.raises(RuntimeError, match="only supported for tool=claude"):
        handlers.build_runtime(session)


def test_oauth_token_requires_secret_file(tmp_path):
    handlers = _make_handlers(tmp_path)
    session = _make_session(tmp_path, secret_file=None)
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ), pytest.raises(RuntimeError, match="missing 'secret_file'"):
        handlers.build_runtime(session)


def test_oauth_token_secret_file_missing_key(tmp_path):
    secret_file = tmp_path / "oauth.env"
    secret_file.write_text("SOMETHING_ELSE=x\n")
    handlers = _make_handlers(tmp_path, secret_env={"SOMETHING_ELSE": "x"})
    session = _make_session(tmp_path, secret_file=secret_file)
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ), pytest.raises(RuntimeError, match="missing CLAUDE_CODE_OAUTH_TOKEN"):
        handlers.build_runtime(session)


# ── ccr path ─────────────────────────────────────────────────────────


def test_ccr_injects_anthropic_base_url(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAWSEAT_CCR_BASE_URL", raising=False)
    handlers = _make_handlers(tmp_path)
    session = _make_session(
        tmp_path, auth_mode="ccr", provider="ccr-local",
    )
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ):
        binary, env = handlers.build_runtime(session)
    assert env["ANTHROPIC_BASE_URL"] == DEFAULT_CCR_BASE_URL
    assert env["ANTHROPIC_AUTH_TOKEN"] == "ccr-local-dummy"


def test_ccr_respects_custom_base_url_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_CCR_BASE_URL", "http://127.0.0.1:9999")
    handlers = _make_handlers(tmp_path)
    session = _make_session(tmp_path, auth_mode="ccr", provider="ccr-local")
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ):
        binary, env = handlers.build_runtime(session)
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9999"


def test_ccr_rejects_non_claude_tool(tmp_path):
    handlers = _make_handlers(tmp_path)
    session = _make_session(
        tmp_path, tool="codex", auth_mode="ccr", provider="ccr-local",
    )
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ), pytest.raises(RuntimeError, match="only supported for tool=claude"):
        handlers.build_runtime(session)


def test_ccr_needs_no_secret_file(tmp_path):
    """CCR holds upstream keys locally — the seat does NOT need a secret."""
    handlers = _make_handlers(tmp_path)
    session = _make_session(
        tmp_path, auth_mode="ccr", provider="ccr-local", secret_file=None,
    )
    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ):
        binary, env = handlers.build_runtime(session)
    assert env["ANTHROPIC_BASE_URL"]  # no "missing secret" error
