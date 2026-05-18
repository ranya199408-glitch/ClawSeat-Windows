from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path("core/skills/memory-oracle/scripts/archive_merged_dispatches.py")


def _run_archive(memory_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--memory-path", str(memory_path), "--default-period", "2026_04", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _write_memory(path: Path) -> None:
    path.write_text(
        """# Memory Index — fake

## Completed

- [DISPATCH_A.md](DISPATCH_A.md) — Alpha task. ✅ MERGED PR #1 on 2026-04-01.
  - implementation detail A
- [DISPATCH_B.md](DISPATCH_B.md) — Beta task. ✅ Done 2026-04-02.
- [DISPATCH_C.md](DISPATCH_C.md) — Gamma task. ✅ PASS 2026-04-03.
- plain-task-d: ✅ MERGED 2026-04-04.
- plain-task-e: ✅ Done 2026-04-05.

## Active

- active-dispatched: 📤 DISPATCHED to builder.
- active-in-flight: 🚀 in flight with planner.
- active-pending: ⏳ pending reviewer.

## Reference

- [reference_a.md](reference_a.md) — keep reference.
- plain-reference: keep plain reference.
""",
        encoding="utf-8",
    )


def test_archive_merged_dispatches_dry_run_has_no_writes(tmp_path: Path) -> None:
    memory_path = tmp_path / "MEMORY.md"
    _write_memory(memory_path)
    before = memory_path.read_text(encoding="utf-8")

    result = _run_archive(memory_path)
    payload = json.loads(result.stdout)

    assert payload["mode"] == "dry-run"
    assert payload["archive_count"] == 5
    assert {entry["task_id"] for entry in payload["entries"]} == {
        "DISPATCH_A",
        "DISPATCH_B",
        "DISPATCH_C",
        "plain-task-d",
        "plain-task-e",
    }
    assert memory_path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "MEMORY_ARCHIVE_2026_04.md").exists()
    assert not list(tmp_path.glob("MEMORY.md.bak.*"))


def test_archive_merged_dispatches_commit_preserves_active_and_is_idempotent(tmp_path: Path) -> None:
    memory_path = tmp_path / "MEMORY.md"
    _write_memory(memory_path)

    first = _run_archive(memory_path, "--commit")
    payload = json.loads(first.stdout)
    archive_path = tmp_path / "MEMORY_ARCHIVE_2026_04.md"
    memory_text = memory_path.read_text(encoding="utf-8")
    archive_text = archive_path.read_text(encoding="utf-8")

    assert payload["mode"] == "commit"
    assert payload["archive_count"] == 5
    assert payload["within_200_lines"] is True
    assert len(payload["archives_written"]) == 1
    assert archive_path.exists()
    assert list(tmp_path.glob("MEMORY.md.bak.*"))

    assert "implementation detail A" not in memory_text
    assert "- DISPATCH_A: ✅ archived → see MEMORY_ARCHIVE_2026_04.md" in memory_text
    assert "- DISPATCH_B: ✅ archived → see MEMORY_ARCHIVE_2026_04.md" in memory_text
    assert "- plain-task-d: ✅ archived → see MEMORY_ARCHIVE_2026_04.md" in memory_text
    assert "active-dispatched: 📤 DISPATCHED" in memory_text
    assert "active-in-flight: 🚀 in flight" in memory_text
    assert "active-pending: ⏳ pending" in memory_text
    assert "reference_a.md" in memory_text

    assert "## DISPATCH_A" in archive_text
    assert "implementation detail A" in archive_text
    assert "## plain-task-e" in archive_text
    assert "active-dispatched" not in archive_text

    second = _run_archive(memory_path, "--commit")
    second_payload = json.loads(second.stdout)
    assert second_payload["archive_count"] == 0
    assert archive_path.read_text(encoding="utf-8") == archive_text
