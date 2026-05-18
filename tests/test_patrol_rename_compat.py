from __future__ import annotations

import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agent_admin_runtime import session_name_for  # noqa: E402
from seat_roles import normalize_seat_role  # noqa: E402


def test_patrol_skill_has_patrol_identity() -> None:
    """After T6 rename: patrol/SKILL.md has patrol identity."""
    assert (_REPO / "core" / "skills" / "patrol").is_dir()
    assert not (_REPO / "core" / "skills" / "qa").exists()
    content = (_REPO / "core" / "skills" / "patrol" / "SKILL.md").read_text(encoding="utf-8")

    assert "patrol" in content.lower() or "cron" in content.lower() or "巡检" in content
    assert not (_SCRIPTS / "patrol_alias.py").exists()
    assert normalize_seat_role("patrol") == "patrol"
    assert session_name_for("install", "patrol", "claude") == "install-patrol-claude"
