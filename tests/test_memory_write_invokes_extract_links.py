from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_MEMORY_WRITE = _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "memory_write.py"
_SPEC = importlib.util.spec_from_file_location("memory_write_under_test", _MEMORY_WRITE)
assert _SPEC is not None and _SPEC.loader is not None
memory_write = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(memory_write)


def test_memory_write_invokes_extract_links(tmp_path: Path, monkeypatch) -> None:
    """memory_write.py triggers extract_links.py as a subprocess after writing."""
    page = tmp_path / "projects" / "install" / "finding" / "test-finding.md"
    page.parent.mkdir(parents=True)
    page.write_text("---\nname: test\n---\n# Test\nSee TASK-999.\n", encoding="utf-8")

    calls: list[list[str]] = []

    def capture_run(cmd, *args, **kwargs):
        calls.append([str(item) for item in cmd])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(memory_write.subprocess, "run", capture_run)
    memory_write._update_link_graph(page, tmp_path)

    extract_calls = [cmd for cmd in calls if "extract_links.py" in " ".join(cmd)]
    assert extract_calls, f"extract_links.py was not called. All calls: {calls}"
    assert "--file" in extract_calls[0]
    assert str(page) in extract_calls[0]
    assert "--memory-dir" in extract_calls[0]
    assert str(tmp_path) in extract_calls[0]
