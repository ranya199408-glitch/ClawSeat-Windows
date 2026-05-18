from __future__ import annotations

from pathlib import Path


def test_watchdog_alerts_on_cross_project_disappear(tmp_path):
    """Watchdog detects disappeared non-project sessions and has alert hooks."""
    project = "install"
    snapshot = tmp_path / "session-snapshot.txt"
    snapshot.write_text("install-memory\narena-memory\ncartooner-memory\n", encoding="utf-8")
    mock_sessions = "install-memory\n"

    previous = set(snapshot.read_text(encoding="utf-8").splitlines())
    current = set(mock_sessions.splitlines())
    disappeared = {
        session
        for session in previous
        if session and not session.startswith(f"{project}-") and session not in current
    }
    assert disappeared == {"arena-memory", "cartooner-memory"}

    script = Path("core/skills/patrol/scripts/patrol_cron.sh").read_text(encoding="utf-8")
    assert "check_cross_project_disappear()" in script
    assert 'check_cross_project_disappear "$project"' in script
    assert "osascript" in script
    assert "send-and-verify.sh" in script
    assert "[ALERT:cross-project-disappear]" in script
