"""Regression tests for the codex `auth.json` write path.

`ResolveHandlers.build_runtime` writes the user's OPENAI_API_KEY into
`<codex_home>/auth.json`. The file must be created with mode 0o600 **at
creation time** — not chmod'd after — so there is no window where the
key is world-readable under a loose umask, and a pre-planted symlink in
the codex home cannot redirect the write.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from core.scripts.agent_admin_resolve import ResolveHandlers, ResolveHooks


def _hooks(tmp_path: Path) -> ResolveHooks:
    return ResolveHooks(
        error_cls=RuntimeError,
        default_tool_args={"codex": []},
        codex_api_provider_configs={},
        common_env=lambda: {},
        ensure_dir=lambda p: p.mkdir(parents=True, exist_ok=True),
        parse_env_file=lambda p: {"OPENAI_API_KEY": "<API_KEY>-KEY"},
        write_codex_api_config=lambda *a, **kw: None,
        write_text=lambda *a, **kw: None,
        load_project=lambda name: SimpleNamespace(repo_root=str(tmp_path / "repo")),
        load_projects=lambda: {},
        load_engineers=lambda: {},
        load_sessions=lambda: {},
        get_current_project_name=lambda _: None,
        display_name_for=lambda e, fallback: fallback,
    )


def _session(tmp_path: Path) -> SimpleNamespace:
    runtime_dir = tmp_path / "runtime"
    return SimpleNamespace(
        runtime_dir=str(runtime_dir),
        tool="codex",
        auth_mode="api",
        bin_path="/usr/bin/codex",
        provider="xcode-best",
        project="install",
        engineer_id="reviewer-1",
        secret_file=str(tmp_path / "reviewer-1.env"),
        launch_args=[],
    )


def test_auth_json_is_created_with_0o600(tmp_path: Path) -> None:
    handlers = ResolveHandlers(_hooks(tmp_path))
    os.umask(0o022)  # the permissive default that caused the original gap
    handlers.build_runtime(_session(tmp_path))

    auth_path = tmp_path / "runtime" / "codex" / "auth.json"
    assert auth_path.exists()
    mode = stat.S_IMODE(auth_path.stat().st_mode)
    assert mode == 0o600, f"auth.json mode={oct(mode)} expected 0o600"
    payload = json.loads(auth_path.read_text())
    assert payload == {"OPENAI_API_KEY": "<API_KEY>-KEY"}


def test_auth_json_overwrite_replaces_existing_file(tmp_path: Path) -> None:
    handlers = ResolveHandlers(_hooks(tmp_path))
    codex_home = tmp_path / "runtime" / "codex"
    codex_home.mkdir(parents=True)
    stale = codex_home / "auth.json"
    stale.write_text('{"OPENAI_API_KEY":"stale"}')
    stale.chmod(0o644)  # deliberately loose to confirm replacement re-applies 0o600

    handlers.build_runtime(_session(tmp_path))

    mode = stat.S_IMODE(stale.stat().st_mode)
    assert mode == 0o600
    assert json.loads(stale.read_text()) == {"OPENAI_API_KEY": "<API_KEY>-KEY"}


def test_auth_json_refuses_to_follow_symlink(tmp_path: Path) -> None:
    """If an attacker plants a symlink at auth.json pointing elsewhere,
    the `unlink()` + `O_EXCL|O_NOFOLLOW` pair must write to the codex
    home, not the symlink target. We verify by asserting the target file
    is never touched."""
    handlers = ResolveHandlers(_hooks(tmp_path))
    codex_home = tmp_path / "runtime" / "codex"
    codex_home.mkdir(parents=True)
    attacker_target = tmp_path / "attacker.txt"
    attacker_target.write_text("original")
    (codex_home / "auth.json").symlink_to(attacker_target)

    handlers.build_runtime(_session(tmp_path))

    # Symlink target must be untouched.
    assert attacker_target.read_text() == "original"
    # auth.json must be a regular file now, not a symlink.
    auth_path = codex_home / "auth.json"
    assert auth_path.is_file() and not auth_path.is_symlink()
    assert stat.S_IMODE(auth_path.lstat().st_mode) == 0o600


def test_auth_json_missing_api_key_raises(tmp_path: Path) -> None:
    hooks = _hooks(tmp_path)
    hooks.parse_env_file = lambda p: {}  # no OPENAI_API_KEY
    handlers = ResolveHandlers(hooks)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        handlers.build_runtime(_session(tmp_path))
