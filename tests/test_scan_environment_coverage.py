"""F7/F8.3 regressions for scan_credentials():

- F7: must cover the canonical ~/.agent-runtime/secrets path (ClawSeat
  seat secrets).
- F8.3: must also detect OAuth evidence (~/.claude/credentials.json and
  CLAUDE_CODE_OAUTH_TOKEN env var) and expose it under `oauth.has_any`,
  so the install flow's P0.3 halt can differentiate "no credentials at
  all" vs "OAuth available but no API key".
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _load_scan_env_with_home(monkeypatch, fake_home: Path):
    """Load scan_environment.py with fake HOME.

    scan_environment.py's `_real_user_home()` probes `pwd.getpwuid` first
    (ignoring $HOME env), so we patch `pwd.getpwuid` in the `pwd` module
    BEFORE loading scan_environment — the module caches `HOME` at import.
    """
    import pwd as _pwd

    class _FakePw:
        pw_dir = str(fake_home)

    monkeypatch.setattr(_pwd, "getpwuid", lambda _uid: _FakePw)

    # Fresh load so module-global HOME is re-evaluated against patched pwd
    mod_path = _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "scan_environment.py"
    spec = importlib.util.spec_from_file_location("scan_env_under_test", mod_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["scan_env_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_scan_credentials_finds_agent_runtime_secrets(monkeypatch, tmp_path):
    fake_home = tmp_path / "fake-user"
    fake_home.mkdir()
    secret = fake_home / ".agent-runtime" / "secrets" / "claude" / "minimax.env"
    secret.parent.mkdir(parents=True)
    secret.write_text("MINIMAX_API_KEY=<MINIMAX_API_KEY>\n", encoding="utf-8")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    mod = _load_scan_env_with_home(monkeypatch, fake_home)
    result = mod.scan_credentials()
    assert "MINIMAX_API_KEY" in result["keys"], (
        f"F7 regression: scan_credentials must find MINIMAX_API_KEY under "
        f"~/.agent-runtime/secrets/. Got: {list(result['keys'].keys())}"
    )


def test_scan_credentials_oauth_credentials_json(monkeypatch, tmp_path):
    """F8.3: presence of ~/.claude/credentials.json → oauth.has_any == True."""
    fake_home = tmp_path / "fake-oauth"
    fake_home.mkdir()
    creds = fake_home / ".claude" / "credentials.json"
    creds.parent.mkdir(parents=True)
    creds.write_text('{"account": "user@example.com", "token": "xxx"}', encoding="utf-8")

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    mod = _load_scan_env_with_home(monkeypatch, fake_home)
    result = mod.scan_credentials()
    assert result["oauth"]["has_any"] is True
    assert result["oauth"]["claude_credentials_json"] is True
    assert str(creds) in result["oauth_sources"]


def test_scan_credentials_oauth_token_env(monkeypatch, tmp_path):
    """F8.3: CLAUDE_CODE_OAUTH_TOKEN env var → oauth.has_any == True."""
    fake_home = tmp_path / "fake-envoauth"
    fake_home.mkdir()

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fixture-claude-oauth-x")

    mod = _load_scan_env_with_home(monkeypatch, fake_home)
    result = mod.scan_credentials()
    assert result["oauth"]["has_any"] is True
    assert result["oauth"]["claude_code_oauth_token_env"] is True
    assert "env:CLAUDE_CODE_OAUTH_TOKEN" in result["oauth_sources"]


def test_scan_credentials_no_auth_at_all(monkeypatch, tmp_path):
    """F8.3: neither API keys nor OAuth → install flow halts at P0.3 case 3."""
    fake_home = tmp_path / "fake-bare"
    fake_home.mkdir()

    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_SANDBOX_HOME_STRICT", "1")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    mod = _load_scan_env_with_home(monkeypatch, fake_home)
    result = mod.scan_credentials()
    assert result["keys"] == {}, f"expected empty keys, got {result['keys']}"
    assert result["oauth"]["has_any"] is False
    assert result["oauth_sources"] == []
