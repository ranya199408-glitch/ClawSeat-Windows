from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

aas = _HELPERS.aas
_make_service = _HELPERS._make_service
_make_session = _HELPERS._make_session


def test_start_engineer_registers_seat_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from state import get_seat, open_db

    db_path = tmp_path / "state.db"
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    monkeypatch.setattr(aas, "real_user_home", lambda: tmp_path / "real-home")
    session = _make_session(
        tmp_path,
        engineer_id="planner",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    svc, _hooks = _make_service(tmp_path, session)
    monkeypatch.setitem(svc._compat_module_globals, "tmux_has_session", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        aas.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    with patch.object(svc, "_assert_session_running"), patch.object(svc, "_run_tmux_with_retry"):
        svc.start_engineer(session)

    with open_db() as conn:
        seat = get_seat(conn, "install", "planner")
    assert seat is not None
    assert seat.status == "live"
    assert seat.role == "planner"
    assert seat.tool == "claude"
    assert seat.auth_mode == "api"
    assert seat.provider == "minimax"
    assert seat.session_name == "install-planner-claude"
    assert seat.workspace == session.workspace
    assert seat.last_heartbeat


def test_start_engineer_state_db_failure_is_nonfatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setattr(aas, "upsert_seat", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")))
    monkeypatch.setattr(aas, "real_user_home", lambda: tmp_path / "real-home")
    session = _make_session(
        tmp_path,
        engineer_id="planner",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    svc, _hooks = _make_service(tmp_path, session)
    monkeypatch.setitem(svc._compat_module_globals, "tmux_has_session", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        aas.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    with patch.object(svc, "_assert_session_running"), patch.object(svc, "_run_tmux_with_retry"):
        svc.start_engineer(session)

    assert "state.db upsert_seat failed (non-fatal): db down" in capsys.readouterr().err


def test_start_engineer_normalises_template_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from state import get_seat, open_db

    db_path = tmp_path / "state.db"
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    monkeypatch.setattr(aas, "real_user_home", lambda: tmp_path / "real-home")
    session = _make_session(
        tmp_path,
        engineer_id="builder",
        tool="codex",
        auth_mode="api",
        provider="xcode-best",
        secret_content="OPENAI_API_KEY=test\n",
    )
    session.project_engineers = {"builder": type("Engineer", (), {"role": "code-builder"})()}
    svc, _hooks = _make_service(tmp_path, session)
    monkeypatch.setitem(svc._compat_module_globals, "tmux_has_session", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        aas.subprocess,
        "run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, "", ""),
    )

    with patch.object(svc, "_assert_session_running"), patch.object(svc, "_run_tmux_with_retry"):
        svc.start_engineer(session)

    with open_db() as conn:
        seat = get_seat(conn, "install", "builder")
    assert seat is not None
    assert seat.role == "builder"
