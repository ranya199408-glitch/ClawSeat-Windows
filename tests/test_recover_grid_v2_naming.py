from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "recover-grid.sh"


def test_recover_grid_session_name_includes_tool_suffix() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'python3 "$agent_admin_bin" session-name "$PRIMARY_SEAT_ID" --project "$PROJECT"' in text
    assert "printf '%s-%s-claude\\n'" in text


def test_recover_grid_window_title_has_workers_suffix() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'WINDOW_TITLE="clawseat-${PROJECT}-workers"' in text


def test_recover_grid_final_verify_uses_tmux_list_clients() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'verify: tmux list-clients -t \\"=$PRIMARY_SESSION\\" per seat' in text
    assert "agent_admin window list-panes" not in text
