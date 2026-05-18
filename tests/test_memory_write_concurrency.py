from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import threading
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "memory-oracle" / "scripts"
_WRITE = _SCRIPTS / "memory_write.py"
_QUERY = _SCRIPTS / "query_memory.py"

sys.path.insert(0, str(_SCRIPTS))
import scan_environment as se  # noqa: E402


def _run_write(memory_dir: Path, content_file: Path, *, title: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_WRITE),
            "--kind",
            "decision",
            "--project",
            "concurrency",
            "--title",
            title,
            "--author",
            "ancestor",
            "--content-file",
            str(content_file),
            "--memory-dir",
            str(memory_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def _run_query(memory_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_QUERY),
            "--status",
            "--memory-dir",
            str(memory_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_concurrent_memory_writes_and_reads_remain_consistent(tmp_path: Path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    content_file = tmp_path / "note.md"
    content_file.write_text("Concurrent memory note.\n", encoding="utf-8")

    worker_count = 8
    barrier = threading.Barrier(worker_count * 2)

    def write_worker(index: int) -> subprocess.CompletedProcess[str]:
        barrier.wait()
        return _run_write(memory_dir, content_file, title=f"note-{index}")

    def read_worker() -> subprocess.CompletedProcess[str]:
        barrier.wait()
        return _run_query(memory_dir)

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count * 2) as pool:
        write_futures = [pool.submit(write_worker, i) for i in range(worker_count)]
        read_futures = [pool.submit(read_worker) for _ in range(worker_count)]
        write_results = [future.result(timeout=30) for future in write_futures]
        read_results = [future.result(timeout=30) for future in read_futures]

    assert all(result.returncode == 0 for result in write_results)
    assert all(result.returncode == 0 for result in read_results)

    note_dir = memory_dir / "projects" / "concurrency" / "decision"
    notes = sorted(note_dir.glob("*.md"))
    assert len(notes) == worker_count
    assert len({note.name for note in notes}) == worker_count

    index = json.loads((memory_dir / "index.json").read_text(encoding="utf-8"))
    assert index["memory_notes_count"] == worker_count
    assert len(index["memory_notes"]) == worker_count

    for result in read_results:
        payload = json.loads(result.stdout)
        assert payload["exists"] is True

    list_result = subprocess.run(
        [
            sys.executable,
            str(_QUERY),
            "--project",
            "concurrency",
            "--kind",
            "decision",
            "--memory-dir",
            str(memory_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert list_result.returncode == 0
    listed = json.loads(list_result.stdout)
    assert len(listed) == worker_count


def test_scan_environment_write_json_uses_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[Path, Path]] = []
    original_replace = se.os.replace

    def recording_replace(src: os.PathLike[str] | str, dst: os.PathLike[str] | str) -> None:
        calls.append((Path(src), Path(dst)))
        original_replace(src, dst)

    monkeypatch.setattr(se.os, "replace", recording_replace)

    out = se.write_json(tmp_path, "credentials", {"alpha": 1, "beta": {"value": "ok"}})

    assert out == tmp_path / "credentials.json"
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8")) == {"alpha": 1, "beta": {"value": "ok"}}
    assert calls and calls[0][1] == out
    assert not any(p.name.startswith("credentials.json.tmp.") for p in tmp_path.iterdir())
