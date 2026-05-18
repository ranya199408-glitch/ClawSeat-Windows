from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DETECT = REPO / "scripts" / "install" / "lib" / "detect.sh"


def test_detect_pty_resource_warns_above_threshold(tmp_path: Path) -> None:
    """PTY detection warns once tmux sessions exceed the 200/256 threshold."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_tmux = bin_dir / "tmux"
    fake_tmux.write_text(
        """#!/usr/bin/env bash
if [[ "${1:-}" == "ls" ]]; then
  i=1
  while [[ "$i" -le 201 ]]; do
    printf 's%s: 1 windows\\n' "$i"
    i=$((i + 1))
  done
fi
""",
        encoding="utf-8",
    )
    fake_tmux.chmod(fake_tmux.stat().st_mode | stat.S_IXUSR)

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_ROOT": str(REPO),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    result = subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(DETECT))}; detect_pty_resource"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"used": 201, "total": 256, "warn": True}
