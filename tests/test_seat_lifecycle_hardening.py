from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = _REPO / "tests" / "test_agent_admin_session_isolation.py"
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_agent_admin_session_isolation_helpers",
    _HELPERS_PATH,
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

aas = _HELPERS.aas
_make_service = _HELPERS._make_service
_make_session = _HELPERS._make_session

if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from core.lib import state  # noqa: E402
from core.lib.state import Seat, get_seat, open_db, pick_least_busy_seat, upsert_seat  # noqa: E402


def _session(tmp_path: Path, *, engineer_id: str, role_provider: str = "xcode-best"):
    return _make_session(
        tmp_path,
        engineer_id=engineer_id,
        tool="claude",
        auth_mode="api",
        provider=role_provider,
        secret_content="OPENAI_API_KEY=<OPENAI_API_KEY>\n",
    )


def test_stop_engineer_marks_seat_stopped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    session = _session(tmp_path, engineer_id="builder-1")
    svc, _hooks = _make_service(tmp_path, session)

    with open_db() as conn:
        upsert_seat(
            conn,
            Seat(
                project=session.project,
                seat_id=session.engineer_id,
                role="builder",
                tool=session.tool,
                auth_mode=session.auth_mode,
                provider=session.provider,
                status="live",
                last_heartbeat="2026-05-05T00:00:00Z",
                session_name=session.session,
                workspace=session.workspace,
            ),
        )

    with patch.object(
        svc,
        "_run_tmux_with_retry",
        return_value=subprocess.CompletedProcess(["tmux"], 0, "", ""),
    ):
        svc.stop_engineer(session)

    with open_db() as conn:
        seat = get_seat(conn, session.project, session.engineer_id)
    assert seat is not None
    assert seat.status == "stopped"
    assert seat.session_name == session.session


def test_pick_least_busy_seat_uses_selected_row_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    with open_db() as conn:
        upsert_seat(
            conn,
            Seat(
                project="install",
                seat_id="builder-1",
                role="builder",
                tool="claude",
                auth_mode="api",
                provider="anthropic",
                status="live",
                last_heartbeat="2026-05-05T00:00:00Z",
                session_name="install-builder-1-claude",
                workspace="/tmp/builder-1",
            ),
        )
        upsert_seat(
            conn,
            Seat(
                project="install",
                seat_id="builder-2",
                role="builder",
                tool="claude",
                auth_mode="api",
                provider="anthropic",
                status="live",
                last_heartbeat="2026-05-05T00:00:00Z",
                session_name="install-builder-2-claude",
                workspace="/tmp/builder-2",
            ),
        )
        monkeypatch.setattr(
            state,
            "get_seat",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pick_least_busy_seat should not refetch the seat row")),
        )
        seat = pick_least_busy_seat(conn, "install", "builder")

    assert seat is not None
    assert seat.seat_id == "builder-1"


def test_record_seat_live_skips_if_session_disappears_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    session = _session(tmp_path, engineer_id="planner")
    svc, hooks = _make_service(tmp_path, session)
    hooks.tmux_has_session.side_effect = [True, False]

    upsert_mock = MagicMock()
    monkeypatch.setitem(svc._compat_module_globals, "upsert_seat", upsert_mock)

    svc._record_seat_live(session, hooks.load_project.return_value)

    upsert_mock.assert_not_called()
    with open_db() as conn:
        assert get_seat(conn, session.project, session.engineer_id) is None


def test_upsert_seat_rejects_stopped_to_live_without_explicit_revival(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "state.db"
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    with open_db() as conn:
        upsert_seat(
            conn,
            Seat(
                project="install",
                seat_id="builder-1",
                role="builder",
                tool="claude",
                auth_mode="api",
                provider="anthropic",
                status="stopped",
                last_heartbeat=None,
                session_name="install-builder-1-claude",
                workspace="/tmp/builder-1",
            ),
        )

        with pytest.raises(ValueError, match="stopped seat"):
            upsert_seat(
                conn,
                Seat(
                    project="install",
                    seat_id="builder-1",
                    role="builder",
                    tool="claude",
                    auth_mode="api",
                    provider="anthropic",
                    status="live",
                    last_heartbeat="2026-05-05T00:00:00Z",
                    session_name="install-builder-1-claude",
                    workspace="/tmp/builder-1",
                ),
            )

        upsert_seat(
            conn,
            Seat(
                project="install",
                seat_id="builder-1",
                role="builder",
                tool="claude",
                auth_mode="api",
                provider="anthropic",
                status="live",
                last_heartbeat="2026-05-05T00:00:00Z",
                session_name="install-builder-1-claude",
                workspace="/tmp/builder-1",
            ),
            allow_stopped_revival=True,
        )

        seat = get_seat(conn, "install", "builder-1")

    assert seat is not None
    assert seat.status == "live"
