from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
AGENT_ADMIN = REPO / "core" / "scripts" / "agent_admin.py"


def _help(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(AGENT_ADMIN), *args, "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_agent_admin_top_level_help_describes_command_groups() -> None:
    output = _help()
    for phrase in (
        "Project registry",
        "tmux session lifecycle",
        "iTerm/tmux project window",
        "Engineer/seat CRUD",
        "Project task TODO",
        "Tool identity",
    ):
        assert phrase in output


def test_agent_admin_template_help_lists_builtin_templates() -> None:
    for args in (("project", "create"), ("project", "bootstrap")):
        output = _help(*args).replace("-\n                        ", "-")
        for template in ("clawseat-engineering", "clawseat-creative", "clawseat-solo"):
            assert template in output
        assert "Template name/path" in output or "Project roster template" in output
