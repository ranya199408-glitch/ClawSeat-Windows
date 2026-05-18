from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_reinstall_kills_only_matching_project_sessions(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    log = tmp_path / "tmux.log"
    osalog = tmp_path / "osascript.log"
    _write_executable(
        bin_dir / "tmux",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "${{1:-}}" == "list-sessions" ]]; then
  printf '%s\\n' demo-memory-claude demo-planner-claude demoish-memory other-demo-builder
  exit 0
fi
printf '%s\\n' "$*" >> {log}
""",
    )
    _write_executable(
        bin_dir / "osascript",
        f"""#!/usr/bin/env bash
cat > {osalog}
exit 0
""",
    )

    probe = f"""
set -euo pipefail
source "{_REPO / 'scripts' / 'install.sh'}"
_kill_existing_project_sessions demo
"""
    result = subprocess.run(
        ["bash", "-c", probe],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PYTHON_BIN": sys.executable,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    killed = log.read_text(encoding="utf-8").splitlines()
    assert "kill-session -t =demo-memory-claude" in killed
    assert "kill-session -t =demo-planner-claude" in killed
    assert all("demoish" not in line and "other-demo" not in line for line in killed)
    assert 'contains "clawseat-demo"' in osalog.read_text(encoding="utf-8")
