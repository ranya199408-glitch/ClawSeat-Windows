from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "cleanup-stale-memories-window.sh"


def _write_osascript_stub(bin_dir: Path, *, output: str = "closed=0", rc: int = 0) -> tuple[Path, Path]:
    args_log = bin_dir / "osascript.args"
    stdin_log = bin_dir / "osascript.stdin"
    stub = bin_dir / "osascript"
    stub.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" > {args_log}
cat > {stdin_log}
printf '%s\\n' {output!r}
exit {rc}
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return args_log, stdin_log


def _run_with_stub(tmp_path: Path, *, output: str = "closed=0", rc: int = 0) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_log, stdin_log = _write_osascript_stub(bin_dir, output=output, rc=rc)
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
    )
    return result, args_log, stdin_log


def test_cleanup_script_builds_defensive_applescript(tmp_path: Path) -> None:
    result, args_log, stdin_log = _run_with_stub(tmp_path, output="closed=1")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "closed=1"
    assert args_log.read_text(encoding="utf-8").strip() == ""
    script = stdin_log.read_text(encoding="utf-8")
    assert 'exists process "iTerm2"' in script
    assert 'application "iTerm2"' in script
    assert 'candidateTitle is "clawseat-memories"' in script
    assert "set staleWindows to missing value" not in script
    assert "set closedWindow to missing value" in script
    assert "set activeSession to current session of activeTab" in script
    assert 'tell activeSession to set markerValue to variable named "user.window_title"' in script
    assert "on memoryWindowMarker" not in script
    assert "close w" not in script
    assert "if markerValue is \"\" and closedWindow is missing value then" in script
    assert "close closedWindow" in script


def test_cleanup_noops_when_iterm_not_running(tmp_path: Path) -> None:
    result, _, stdin_log = _run_with_stub(tmp_path, output="iterm_not_running")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "iterm_not_running"
    assert 'exists process "iTerm2"' in stdin_log.read_text(encoding="utf-8")


def test_cleanup_swallow_osascript_failure(tmp_path: Path) -> None:
    result, _, _ = _run_with_stub(tmp_path, output="application unavailable", rc=42)

    assert result.returncode == 0
    assert "warn: cleanup-stale-memories-window skipped: application unavailable" in result.stderr


def test_cleanup_outputs_warning_when_stale_window_closed(tmp_path: Path) -> None:
    result, _, _ = _run_with_stub(tmp_path, output="closed=1")

    assert result.returncode == 0, result.stderr
    assert "warn: cleanup-stale-memories-window closed stale window(s): 1" in result.stderr
