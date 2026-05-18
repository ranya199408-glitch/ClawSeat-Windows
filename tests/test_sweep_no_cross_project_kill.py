from __future__ import annotations

import subprocess
from unittest.mock import patch


def test_sweep_guard_detects_cross_project_kill(monkeypatch):
    """Sweep guard sees non-current-project sessions disappear."""
    project = "install"
    responses = [
        b"install-memory\narena-memory\ncartooner-memory\n",
        b"install-memory\n",
    ]

    with patch("subprocess.check_output", side_effect=responses):
        monkeypatch.setenv("CLAWSEAT_PROJECT", project)
        raw_before = subprocess.check_output(["tmux"]).decode().splitlines()
        before = {s.strip() for s in raw_before if s.strip() and not s.strip().startswith(f"{project}-")}
        raw_after = subprocess.check_output(["tmux"]).decode().splitlines()
        after = {s.strip() for s in raw_after if s.strip() and not s.strip().startswith(f"{project}-")}

    killed = before - after
    assert killed == {"arena-memory", "cartooner-memory"}
