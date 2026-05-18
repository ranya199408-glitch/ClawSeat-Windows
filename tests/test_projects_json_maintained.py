from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_update_projects_json_registers_reinstalls_and_uninstalls(tmp_path: Path) -> None:
    home = tmp_path / "home"
    registry_home = tmp_path / ".clawseat"
    probe = f"""
set -euo pipefail
source "{_REPO / 'scripts' / 'install.sh'}" >/dev/null
PROJECT=demo
PROJECT_REPO_ROOT=/repo/demo
CLAWSEAT_TEMPLATE_NAME=clawseat-creative
PRIMARY_SEAT_ID=memory
MEMORY_TOOL=claude
MEMORY_TOOL_EXPLICIT=0
PROVIDER_MODE=oauth
_update_projects_json install demo
FORCE_REINSTALL=1
_update_projects_json reinstall demo
cp "$CLAWSEAT_REGISTRY_HOME/projects.json" "{tmp_path / 'registered.json'}"
_update_projects_json uninstall demo
"""
    result = subprocess.run(
        ["bash", "-c", probe],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "CLAWSEAT_REGISTRY_HOME": str(registry_home),
            "PYTHON_BIN": sys.executable,
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    registered = json.loads((tmp_path / "registered.json").read_text(encoding="utf-8"))
    assert registered["projects"][0]["name"] == "demo"
    assert registered["projects"][0]["template_name"] == "clawseat-creative"
    assert registered["projects"][0]["repo_path"] == "/repo/demo"
    data = json.loads((registry_home / "projects.json").read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert data["projects"] == []
    backup = json.loads((registry_home / "projects.json.bak").read_text(encoding="utf-8"))
    assert backup["projects"] == []
