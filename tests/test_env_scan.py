from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_ENV_SCAN_PATH = _REPO / "scripts" / "env_scan.py"
_SPEC = importlib.util.spec_from_file_location("env_scan_under_test", _ENV_SCAN_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ENV_SCAN = importlib.util.module_from_spec(_SPEC)
sys.modules["env_scan_under_test"] = _ENV_SCAN
_SPEC.loader.exec_module(_ENV_SCAN)


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def _auth_method_present(
    data: dict[str, object],
    *,
    tool: str,
    auth_mode: str,
    provider: str,
) -> bool:
    auth_methods = data.get("auth_methods", [])
    return any(
        entry.get("tool") == tool
        and entry.get("auth_mode") == auth_mode
        and entry.get("provider") == provider
        for entry in auth_methods
    )


@pytest.mark.parametrize(
    ("relpath", "key_line", "url_line", "provider_key", "tool", "auth_mode", "provider"),
    [
        (
            ".agent-runtime/secrets/codex/xcode.env",
            "OPENAI_API_KEY=<OPENAI_API_KEY>",
            "OPENAI_BASE_URL=https://api.xcode.best/v1",
            "xcode-best",
            "codex",
            "api",
            "xcode-best",
        ),
        (
            ".agent-runtime/secrets/claude/xcode.env",
            "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>",
            "ANTHROPIC_BASE_URL=https://xcode.best",
            "xcode-best",
            "claude",
            "api",
            "xcode-best",
        ),
        (
            ".agent-runtime/secrets/claude/ark.env",
            "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>",
            "ANTHROPIC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding",
            "ark",
            "claude",
            "api",
            "ark",
        ),
        (
            ".agent-runtime/secrets/claude/minimax.env",
            "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>,
            "ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic",
            "minimax",
            "claude",
            "api",
            "minimax",
        ),
    ],
)
def test_scan_requires_provider_url_in_secret_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    relpath: str,
    key_line: str,
    url_line: str,
    provider_key: str,
    tool: str,
    auth_mode: str,
    provider: str,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_SCAN_HOME", str(fake_home))
    _clear_auth_env(monkeypatch)

    secret = fake_home / relpath
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text(f"{key_line}\n", encoding="utf-8")

    data = _ENV_SCAN.scan()
    assert data["providers"][provider_key] is False
    assert not _auth_method_present(
        data,
        tool=tool,
        auth_mode=auth_mode,
        provider=provider,
    )

    secret.write_text(f"{key_line}\n{url_line}\n", encoding="utf-8")

    data = _ENV_SCAN.scan()
    assert data["providers"][provider_key] is True
    assert _auth_method_present(
        data,
        tool=tool,
        auth_mode=auth_mode,
        provider=provider,
    )


@pytest.mark.parametrize("base_var", ["OPENAI_BASE_URL", "OPENAI_API_BASE"])
def test_scan_accepts_codex_xcode_env_base_url_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    base_var: str,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_SCAN_HOME", str(fake_home))
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-codex-xcode")
    monkeypatch.setenv(base_var, "https://api.xcode.best/v1")

    data = _ENV_SCAN.scan()

    assert data["providers"]["xcode-best"] is True
    assert _auth_method_present(
        data,
        tool="codex",
        auth_mode="api",
        provider="xcode-best",
    )


def test_scan_accepts_claude_ark_env_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_SCAN_HOME", str(fake_home))
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-claude-ark")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding")

    data = _ENV_SCAN.scan()

    assert data["providers"]["ark"] is True
    assert _auth_method_present(
        data,
        tool="claude",
        auth_mode="api",
        provider="ark",
    )


def test_scan_rejects_claude_ark_env_without_volces_domain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("CLAWSEAT_SCAN_HOME", str(fake_home))
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fixture-claude-ark")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

    data = _ENV_SCAN.scan()

    assert data["providers"]["ark"] is False
    assert not _auth_method_present(
        data,
        tool="claude",
        auth_mode="api",
        provider="ark",
    )
