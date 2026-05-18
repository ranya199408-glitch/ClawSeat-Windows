from __future__ import annotations

import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from core.lib.state import Seat, get_seat, open_db, upsert_seat  # noqa: E402
from reconcile_seat_states import parse_session_name, reconcile  # noqa: E402


def _write_project(home: Path, name: str, seats: list[str]) -> None:
    path = home / ".agents" / "projects" / name / "project.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "[" + ", ".join(f'"{seat}"' for seat in seats) + "]"
    path.write_text(
        "\n".join(
            [
                "version = 1",
                f'name = "{name}"',
                'repo_root = "/tmp/repo"',
                'monitor_session = "monitor"',
                f"engineers = {rendered}",
                f"monitor_engineers = {rendered}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_session(home: Path, project: str, seat: str, session_name: str) -> None:
    path = home / ".agents" / "sessions" / project / seat / "session.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "version = 1",
                f'project = "{project}"',
                f'engineer_id = "{seat}"',
                'tool = "codex"',
                'auth_mode = "api"',
                'provider = "xcode-best"',
                'identity = "id"',
                f'workspace = "{home}/.agents/workspaces/{project}/{seat}"',
                'runtime_dir = ""',
                f'session = "{session_name}"',
                'bin_path = ""',
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_parse_session_name_handles_hyphenated_project_and_seat() -> None:
    known = {
        "lotus-radar": type("KnownProject", (), {"name": "lotus-radar", "seats": {"builder-1", "planner"}})(),
    }
    parsed = parse_session_name("lotus-radar-builder-1-gpt-5", known)
    assert parsed is not None
    assert parsed.project == "lotus-radar"
    assert parsed.seat_id == "builder-1"
    assert parsed.tool == "gpt-5"


def test_reconcile_registers_untracked_tmux_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    db_path = tmp_path / "state.db"
    _write_project(home, "lotus-radar", ["memory", "planner"])
    _write_session(home, "lotus-radar", "planner", "lotus-radar-planner-codex")
    tmux_output = tmp_path / "tmux.txt"
    tmux_output.write_text("lotus-radar-planner-codex\nnot-a-clawseat-session\n", encoding="utf-8")
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(home))
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))

    counts = reconcile(project="lotus-radar", tmux_output_file=str(tmux_output))

    assert counts == {"live": 1, "dead": 0, "skipped": 1}
    with open_db() as conn:
        seat = get_seat(conn, "lotus-radar", "planner")
    assert seat is not None
    assert seat.status == "live"
    assert seat.role == "planner"
    assert seat.tool == "codex"
    assert seat.auth_mode == "api"
    assert seat.provider == "xcode-best"
    assert seat.session_name == "lotus-radar-planner-codex"


def test_reconcile_marks_missing_tmux_session_dead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    db_path = tmp_path / "state.db"
    _write_project(home, "install", ["memory", "builder"])
    tmux_output = tmp_path / "tmux.txt"
    tmux_output.write_text("install-memory-claude\n", encoding="utf-8")
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(home))
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    with open_db() as conn:
        upsert_seat(
            conn,
            Seat(
                project="install",
                seat_id="builder",
                role="builder",
                tool="claude",
                auth_mode="oauth",
                provider="anthropic",
                status="live",
                last_heartbeat="2026-04-27T00:00:00Z",
                session_name="install-builder-claude",
                workspace="/tmp/workspace",
            ),
        )

    counts = reconcile(project="install", tmux_output_file=str(tmux_output))

    assert counts["dead"] == 1
    with open_db() as conn:
        seat = get_seat(conn, "install", "builder")
    assert seat is not None
    assert seat.status == "dead"
    assert seat.provider == "anthropic"
    assert seat.workspace == "/tmp/workspace"


def test_reconcile_live_update_preserves_existing_record_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    db_path = tmp_path / "state.db"
    _write_project(home, "install", ["builder"])
    tmux_output = tmp_path / "tmux.txt"
    tmux_output.write_text("install-builder-claude\n", encoding="utf-8")
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(home))
    monkeypatch.setenv("CLAWSEAT_STATE_DB", str(db_path))
    with open_db() as conn:
        upsert_seat(
            conn,
            Seat(
                project="install",
                seat_id="builder",
                role="builder",
                tool="claude",
                auth_mode="oauth",
                provider="anthropic",
                status="dead",
                session_name="install-builder-claude",
                workspace="/tmp/preserved",
            ),
        )

    reconcile(project="install", tmux_output_file=str(tmux_output))

    with open_db() as conn:
        seat = get_seat(conn, "install", "builder")
    assert seat is not None
    assert seat.status == "live"
    assert seat.provider == "anthropic"
    assert seat.workspace == "/tmp/preserved"
