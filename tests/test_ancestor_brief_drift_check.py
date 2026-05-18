from __future__ import annotations

import os
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "memory-brief-mtime-check.sh"


def _write_tmux_stub(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "tmux").write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "display-message" ]]; then
  printf '%s\n' "${TMUX_SESSION_CREATED:?}"
  exit 0
fi
printf 'unexpected tmux argv: %s\n' "$*" >&2
exit 2
""",
        encoding="utf-8",
    )
    (bin_dir / "tmux").chmod(0o755)


def _run_check(tmp_path: Path, *, brief_exists: bool, brief_mtime: int | None, session_created: int | None, with_target: bool) -> subprocess.CompletedProcess[str]:
    brief = tmp_path / "memory-bootstrap.md"
    if brief_exists:
        brief.write_text("brief\n", encoding="utf-8")
        if brief_mtime is not None:
            os.utime(brief, (brief_mtime, brief_mtime))

    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "CLAWSEAT_MEMORY_BRIEF": str(brief),
    }
    if with_target:
        env["CLAWSEAT_MEMORY_SESSION"] = "smoke01-memory"
        env["TMUX_PANE"] = "%1"
    if session_created is not None:
        env["TMUX_SESSION_CREATED"] = str(session_created)

    return subprocess.run(
        ["bash", str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )


def test_reports_drift_when_brief_is_newer_than_session_start(tmp_path: Path) -> None:
    _write_tmux_stub(tmp_path / "bin")
    result = _run_check(
        tmp_path,
        brief_exists=True,
        brief_mtime=1_700_000_010,
        session_created=1_700_000_000,
        with_target=True,
    )

    assert result.returncode == 1, result.stderr
    assert "BRIEF_DRIFT_DETECTED" in result.stdout
    assert "memory_started_unix=1700000000" in result.stdout
    assert "brief_mtime_unix=1700000010" in result.stdout
    assert "memory-bootstrap.md" in result.stdout


def test_allows_brief_when_it_is_not_newer_than_session_start(tmp_path: Path) -> None:
    _write_tmux_stub(tmp_path / "bin")
    result = _run_check(
        tmp_path,
        brief_exists=True,
        brief_mtime=1_700_000_000,
        session_created=1_700_000_010,
        with_target=True,
    )

    assert result.returncode == 0, result.stderr
    assert "BRIEF_DRIFT_DETECTED" not in result.stdout


def test_ignores_missing_brief(tmp_path: Path) -> None:
    _write_tmux_stub(tmp_path / "bin")
    result = _run_check(
        tmp_path,
        brief_exists=False,
        brief_mtime=None,
        session_created=1_700_000_000,
        with_target=True,
    )

    assert result.returncode == 0, result.stderr
    assert "BRIEF_DRIFT_DETECTED" not in result.stdout


def test_ignores_missing_tmux_target(tmp_path: Path) -> None:
    _write_tmux_stub(tmp_path / "bin")
    result = _run_check(
        tmp_path,
        brief_exists=True,
        brief_mtime=1_700_000_010,
        session_created=None,
        with_target=False,
    )

    assert result.returncode == 0, result.stderr
    assert "BRIEF_DRIFT_DETECTED" not in result.stdout
