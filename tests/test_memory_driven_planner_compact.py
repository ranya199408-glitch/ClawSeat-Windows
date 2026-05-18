from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECK_MARKER = ROOT / "core" / "skills" / "memory-oracle" / "scripts" / "check_compact_marker.py"
WAVE_COUNT = ROOT / "core" / "skills" / "memory-oracle" / "scripts" / "wave_count_since_compact.py"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def test_marker_present() -> None:
    result = _run(CHECK_MARKER, "--text", "foo [memory: compact-me] bar")

    assert result.returncode == 0
    assert "marker=present" in result.stdout


def test_marker_absent() -> None:
    result = _run(CHECK_MARKER, "--text", "no marker here")

    assert result.returncode == 0
    assert "marker=absent" in result.stdout


def test_marker_with_other_brackets() -> None:
    result = _run(CHECK_MARKER, "--text", "[planner: foo] still no compact token")

    assert result.returncode == 0
    assert "marker=absent" in result.stdout


def test_wave_count_under_threshold(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.md"
    status.write_text("phase=CLOSED\nphase=CLOSED\nphase=CLOSED\n", encoding="utf-8")

    result = _run(WAVE_COUNT, "--status-file", str(status), "--threshold", "5")

    assert result.returncode == 0
    assert "triggered=false" in result.stdout
    assert "waves_since=3" in result.stdout


def test_wave_count_over_threshold(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.md"
    status.write_text(
        "phase=CLOSED\nphase=CLOSED\nphase=CLOSED\nphase=CLOSED\nphase=CLOSED\nphase=CLOSED\n",
        encoding="utf-8",
    )

    result = _run(WAVE_COUNT, "--status-file", str(status), "--threshold", "5")

    assert result.returncode == 0
    assert "triggered=true" in result.stdout
    assert "waves_since=6" in result.stdout


def test_wave_count_reset_after_compact(tmp_path: Path) -> None:
    status = tmp_path / "STATUS.md"
    status.write_text(
        "phase=CLOSED\nphase=CLOSED\nphase=CLOSED\n"
        "compacted planner @ 2026-05-07T00:00:00Z\n"
        "phase=CLOSED\nphase=CLOSED\nphase=CLOSED\n",
        encoding="utf-8",
    )

    result = _run(WAVE_COUNT, "--status-file", str(status), "--threshold", "5")

    assert result.returncode == 0
    assert "triggered=false" in result.stdout
    assert "waves_since=3" in result.stdout


def test_status_file_missing(tmp_path: Path) -> None:
    status = tmp_path / "missing-STATUS.md"

    result = _run(WAVE_COUNT, "--status-file", str(status), "--threshold", "5")

    assert result.returncode == 0
    assert "triggered=false" in result.stdout
    assert "waves_since=0" in result.stdout
