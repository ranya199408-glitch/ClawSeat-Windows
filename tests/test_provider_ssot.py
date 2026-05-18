from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[1]
for path in (REPO / "core" / "lib", REPO / "core" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_admin_provider import ProviderHandlers
from providers import (
    Provider,
    add_provider,
    get_provider,
    list_providers,
    migrate_legacy_provider_secrets,
    provider_secret_file_path,
    read_providers,
    rename_provider,
)


def _set_home(monkeypatch: object, home: Path) -> None:
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(home))


def _write_session_toml(path: Path, provider: str, secret_file: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                f'provider = "{provider}"',
                f'secret_file = "{secret_file}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_provider_cli_add_get_list_redacts_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    home = tmp_path / "home"
    _set_home(monkeypatch, home)

    handlers = ProviderHandlers(RuntimeError)
    monkeypatch.setattr(sys, "stdin", io.StringIO("fixture-provider-value\n"))

    rc = handlers.add(
        SimpleNamespace(
            name="anthropic-console",
            tool="claude",
            kind="api_key",
            family="anthropic",
            base_url="",
            model="",
            secret_stdin=True,
            json=True,
        )
    )
    assert rc == 0

    output = capsys.readouterr()
    assert "fixture-provider-value" not in output.out
    assert "fixture-provider-value" not in output.err

    payload = json.loads(output.out)
    provider = payload["provider"]
    secret_file = home / ".agents" / "secrets" / "claude" / "anthropic-console.env"
    assert provider["secret_file"] == str(secret_file)
    assert provider["base_url"] == "https://api.anthropic.com"
    assert provider["has_secret"] is True
    assert secret_file.read_text(encoding="utf-8") == "fixture-provider-value\n"
    assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600

    get_rc = handlers.get(SimpleNamespace(name="anthropic-console", json=True))
    assert get_rc == 0
    get_output = capsys.readouterr()
    assert "fixture-provider-value" not in get_output.out
    assert "fixture-provider-value" not in get_output.err
    get_payload = json.loads(get_output.out)
    assert get_payload["provider"]["name"] == "anthropic-console"
    assert get_payload["provider"]["has_secret"] is True

    list_rc = handlers.list(SimpleNamespace(tool="claude", json=True))
    assert list_rc == 0
    list_output = capsys.readouterr()
    assert "fixture-provider-value" not in list_output.out
    assert "fixture-provider-value" not in list_output.err
    list_payload = json.loads(list_output.out)
    assert [item["name"] for item in list_payload["providers"]] == ["anthropic-console"]


def test_legacy_provider_migration_renames_per_engineer_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    _set_home(monkeypatch, home)

    legacy_dir = home / ".agents" / "secrets" / "claude" / "minimax"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    first = legacy_dir / "engineer-a.env"
    second = legacy_dir / "engineer-b.env"
    first.write_text(
        "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\nMINIMAX_API_HOST=https://api.minimaxi.com/anthropic\n",
        encoding="utf-8",
    )
    expected_secret = (
        "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\nMINIMAX_API_HOST=https://api.minimaxi.com/anthropic\n"
    )
    second.write_text(expected_secret, encoding="utf-8")
    os.utime(first, (1_700_000_000, 1_700_000_000))
    os.utime(second, (1_700_000_100, 1_700_000_100))

    results = migrate_legacy_provider_secrets(home=home)
    assert results

    providers = read_providers(home / ".agents" / "providers.toml")
    provider = providers.providers["minimax"]
    assert provider.tool == "claude"
    assert provider.family == "minimax"
    assert provider.kind == "api_key"
    assert provider.secret_file == str(home / ".agents" / "secrets" / "claude" / "minimax.env")
    assert provider.has_secret is True

    secret_file = home / ".agents" / "secrets" / "claude" / "minimax.env"
    assert secret_file.read_text(encoding="utf-8") == expected_secret
    migrated = sorted(legacy_dir.glob("*.migrated-*"))
    assert len(migrated) == 2
    assert all(path.suffixes[-1].startswith(".migrated-") or ".migrated-" in path.name for path in migrated)


def test_rename_provider_updates_session_reference_and_secret_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    _set_home(monkeypatch, home)

    result = add_provider(
        Provider(
            name="anthropic-console",
            tool="claude",
            kind="api_key",
            family="anthropic",
            secret_file="",
            base_url="",
            model="",
        ),
        "fixture-rename-value\n",
    )
    assert result.provider.secret_file.endswith("anthropic-console.env")

    session_toml = home / ".agents" / "sessions" / "demo" / "seat-a" / "session.toml"
    _write_session_toml(session_toml, "anthropic-console", Path(result.provider.secret_file))

    rename_result = rename_provider("anthropic-console", "anthropic-console-v2")
    assert rename_result.provider.name == "anthropic-console-v2"
    assert rename_result.provider.secret_file.endswith("anthropic-console-v2.env")

    assert not (home / ".agents" / "secrets" / "claude" / "anthropic-console.env").exists()
    assert (home / ".agents" / "secrets" / "claude" / "anthropic-console-v2.env").exists()
    session_text = session_toml.read_text(encoding="utf-8")
    assert 'provider = "anthropic-console-v2"' in session_text
    assert 'secret_file = "' in session_text
    assert "anthropic-console-v2.env" in session_text
