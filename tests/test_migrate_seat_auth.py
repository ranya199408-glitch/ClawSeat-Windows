"""A1 tests for migrate_seat_auth.py.

Covers: plan output, apply --dry-run, apply 6 seats, missing token/secret
→ exit 2, idempotent re-run, skips unknown seats, plus anthropic-console
matrix and build_runtime coverage.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))

from agent_admin_config import (  # noqa: E402
    SUPPORTED_RUNTIME_MATRIX,
    supported_runtime_summary_lines,
    validate_runtime_combo,
)
from agent_admin_resolve import ResolveHandlers, ResolveHooks  # noqa: E402
import migrate_seat_auth as msa  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────


def _write_session_toml(base: Path, project: str, seat: str, auth_mode: str, provider: str) -> None:
    p = base / project / seat
    p.mkdir(parents=True, exist_ok=True)
    (p / "session.toml").write_text(
        f'auth_mode = "{auth_mode}"\nprovider = "{provider}"\ntool = "claude"\n'
    )


def _setup_sessions(base: Path, overrides: dict | None = None) -> None:
    """Write session.tomls at target state by default; overrides can set per-seat values."""
    defaults = {
        ("install", "koder"):      ("oauth", "anthropic"),
        ("install", "planner"):    ("oauth", "anthropic"),
        ("install", "builder-1"):  ("oauth", "anthropic"),
        ("install", "builder-2"):  ("oauth", "anthropic"),
        ("myproject", "planner"):  ("oauth", "anthropic"),
        ("audit", "builder-1"):    ("oauth", "anthropic"),
    }
    merged = {**defaults, **(overrides or {})}
    for (project, seat), (mode, provider) in merged.items():
        _write_session_toml(base, project, seat, mode, provider)


def _write_secret(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _patched_msa(tmp_path: Path, *, with_oauth_token=True, with_console_key=True):
    """Patch msa module-level paths to tmp_path for isolation."""
    agents_root = tmp_path / ".agents"
    sessions_root = agents_root / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    oauth_secret = agents_root / ".env.global"
    console_secret = agents_root / "secrets" / "claude" / "anthropic-console.env"

    if with_oauth_token:
        _write_secret(oauth_secret, "export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>\n")
    if with_console_key:
        _write_secret(console_secret, "ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>\n")

    patches = {
        "msa.AGENTS_ROOT": agents_root,
        "msa._OAUTH_TOKEN_SECRET": oauth_secret,
        "msa._ANTHROPIC_CONSOLE_SECRET": console_secret,
    }
    return sessions_root, patches


# ── Matrix: anthropic-console registered ─────────────────────────────


def test_matrix_includes_anthropic_console():
    providers = SUPPORTED_RUNTIME_MATRIX["claude"]["api"]
    assert "anthropic-console" in providers


def test_validate_accepts_anthropic_console():
    validate_runtime_combo("claude", "api", "anthropic-console")


def test_summary_mentions_anthropic_console():
    lines = "\n".join(supported_runtime_summary_lines())
    assert "anthropic-console" in lines


# ── build_runtime: anthropic-console path ────────────────────────────


def _make_handlers(tmp_path, secret_env=None):
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
    handlers.hooks.sessions_root = tmp_path
    return handlers


def _make_session(tmp_path, *, tool="claude", auth_mode="api",
                  provider="anthropic-console", secret_file=None):
    runtime_dir = tmp_path / "rt"
    runtime_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        engineer_id="builder-2",
        project="install",
        tool=tool,
        auth_mode=auth_mode,
        provider=provider,
        identity="claude.api.anthropic-console.install.builder-2",
        workspace=str(tmp_path),
        runtime_dir=str(runtime_dir),
        session="install-builder-2-claude",
        bin_path="/usr/bin/claude",
        monitor=True,
        legacy_sessions=[],
        launch_args=[],
        secret_file=str(secret_file) if secret_file else "",
        wrapper="",
    )


def test_anthropic_console_injects_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    secret_file = tmp_path / "console.env"
    secret_file.write_text("ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>\n")
    handlers = _make_handlers(tmp_path, secret_env={"ANTHROPIC_API_KEY": "fixture-anthropic-api-test"})
    session = _make_session(tmp_path, secret_file=secret_file)

    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ):
        _, env = handlers.build_runtime(session)

    assert env["ANTHROPIC_API_KEY"] == "fixture-anthropic-api-test"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_anthropic_console_clears_stale_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "stale-token")
    secret_file = tmp_path / "console.env"
    secret_file.write_text("ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>\n")
    handlers = _make_handlers(tmp_path, secret_env={"ANTHROPIC_API_KEY": "fixture-anthropic-api-test"})
    session = _make_session(tmp_path, secret_file=secret_file)

    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ):
        _, env = handlers.build_runtime(session)

    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_anthropic_console_missing_api_key_raises(tmp_path):
    secret_file = tmp_path / "console.env"
    secret_file.write_text("OTHER_KEY=x\n")
    handlers = _make_handlers(tmp_path, secret_env={"OTHER_KEY": "x"})
    session = _make_session(tmp_path, secret_file=secret_file)

    with mock.patch(
        "agent_admin_resolve.ensure_runtime_home_links",
        return_value=SimpleNamespace(actions=[]),
    ), pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        handlers.build_runtime(session)


# ── plan command ──────────────────────────────────────────────────────


def test_plan_prints_mapping_table(tmp_path, capsys):
    sessions_root, patches = _patched_msa(tmp_path)
    _setup_sessions(sessions_root)

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read):
        rc = msa.cmd_plan(None)

    assert rc == 0
    out = capsys.readouterr().out
    # All 6 seats appear.
    assert "koder" in out
    assert "planner" in out
    assert "builder-1" in out
    assert "builder-2" in out
    assert "myproject" in out
    assert "audit" in out
    assert "oauth_token" in out
    assert "anthropic-console" in out


# ── apply --dry-run ───────────────────────────────────────────────────


def test_apply_dry_run_shows_commands_no_changes(tmp_path, capsys):
    sessions_root, patches = _patched_msa(tmp_path)
    _setup_sessions(sessions_root)

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read), \
         mock.patch("subprocess.run") as mock_run:
        args = SimpleNamespace(dry_run=True)
        rc = msa.cmd_apply(args)

    assert rc == 0
    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "Dry run" in out
    assert "agent-admin" in out


# ── apply: 6 seats updated ────────────────────────────────────────────


def test_apply_updates_all_six_seats(tmp_path, capsys):
    sessions_root, patches = _patched_msa(tmp_path)
    _setup_sessions(sessions_root)

    call_count = [0]

    def fake_run(cmd, **kw):
        # Simulate agent-admin rewriting the session.toml.
        seat = cmd[cmd.index("--engineer") + 1]
        project = cmd[cmd.index("--project") + 1]
        mode = cmd[cmd.index("--mode") + 1]
        provider = cmd[cmd.index("--provider") + 1]
        _write_session_toml(sessions_root, project, seat, mode, provider)
        call_count[0] += 1
        return SimpleNamespace(returncode=0, stderr="")

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read), \
         mock.patch("subprocess.run", side_effect=fake_run):
        args = SimpleNamespace(dry_run=False)
        rc = msa.cmd_apply(args)

    assert rc == 0
    assert call_count[0] == 6


# ── apply: idempotent ─────────────────────────────────────────────────


def test_apply_idempotent(tmp_path, capsys):
    """Re-running after full migration → 0 changes, no agent-admin calls."""
    sessions_root, patches = _patched_msa(tmp_path)
    # Pre-write all sessions at their target state.
    for (project, seat), (mode, provider) in msa.TARGET_MAPPING.items():
        _write_session_toml(sessions_root, project, seat, mode, provider)

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read), \
         mock.patch("subprocess.run") as mock_run:
        args = SimpleNamespace(dry_run=False)
        rc = msa.cmd_apply(args)

    assert rc == 0
    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "Already migrated" in out


# ── apply: missing CLAUDE_CODE_OAUTH_TOKEN → exit 2 ──────────────────


def test_apply_missing_oauth_token_exits_2(tmp_path, capsys):
    sessions_root, patches = _patched_msa(tmp_path, with_oauth_token=False)
    _setup_sessions(sessions_root)

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read):
        args = SimpleNamespace(dry_run=False)
        rc = msa.cmd_apply(args)

    assert rc == 2
    err = capsys.readouterr().err
    assert "CLAUDE_CODE_OAUTH_TOKEN" in err


# ── apply: missing ANTHROPIC_API_KEY → exit 2 ────────────────────────


def test_apply_missing_console_secret_exits_2(tmp_path, capsys):
    sessions_root, patches = _patched_msa(tmp_path, with_console_key=False)
    _setup_sessions(sessions_root)

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read):
        args = SimpleNamespace(dry_run=False)
        rc = msa.cmd_apply(args)

    assert rc == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err


# ── apply: skips seats not in session store ───────────────────────────


def test_apply_skips_missing_session_toml(tmp_path, capsys):
    sessions_root, patches = _patched_msa(tmp_path)
    # Only write some of the sessions; others should be gracefully skipped.
    _write_session_toml(sessions_root, "install", "koder", "oauth", "anthropic")

    call_count = [0]

    def fake_run(cmd, **kw):
        seat = cmd[cmd.index("--engineer") + 1]
        project = cmd[cmd.index("--project") + 1]
        mode = cmd[cmd.index("--mode") + 1]
        provider = cmd[cmd.index("--provider") + 1]
        _write_session_toml(sessions_root, project, seat, mode, provider)
        call_count[0] += 1
        return SimpleNamespace(returncode=0, stderr="")

    def patched_read(project, seat):
        path = sessions_root / project / seat / "session.toml"
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    with mock.patch.multiple("migrate_seat_auth", **{k.split(".", 1)[1]: v for k, v in patches.items()}), \
         mock.patch("migrate_seat_auth._read_session_toml", side_effect=patched_read), \
         mock.patch("subprocess.run", side_effect=fake_run):
        args = SimpleNamespace(dry_run=False)
        rc = msa.cmd_apply(args)

    assert rc == 0
    assert call_count[0] == 1  # only koder was present


# ── preflight helper unit tests ───────────────────────────────────────


def test_check_env_file_has_key_export_syntax(tmp_path):
    f = tmp_path / "test.env"
    f.write_text("export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>\n")
    assert msa._check_env_file_has_key(f, "CLAUDE_CODE_OAUTH_TOKEN") is True


def test_check_env_file_has_key_plain_syntax(tmp_path):
    f = tmp_path / "test.env"
    f.write_text("ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>\n")
    assert msa._check_env_file_has_key(f, "ANTHROPIC_API_KEY") is True


def test_check_env_file_has_key_missing_file(tmp_path):
    assert msa._check_env_file_has_key(tmp_path / "nope.env", "KEY") is False


def test_check_env_file_has_key_empty_value(tmp_path):
    f = tmp_path / "test.env"
    f.write_text("ANTHROPIC_API_KEY=\n")
    assert msa._check_env_file_has_key(f, "ANTHROPIC_API_KEY") is False
