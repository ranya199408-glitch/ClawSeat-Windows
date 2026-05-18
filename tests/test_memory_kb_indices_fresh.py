from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCAN_INDEX = REPO / "core" / "skills" / "memory-oracle" / "scripts" / "scan_index.py"
INSTALL = REPO / "scripts" / "install.sh"


def _load_scan_index():
    spec = importlib.util.spec_from_file_location("scan_index_w2", SCAN_INDEX)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_record(home: Path) -> None:
    path = home / ".agents" / "memory" / "projects" / "install" / "finding" / "one.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        "ts: 2026-04-30T00:00:00Z\n"
        "project: install\n"
        "kind: finding\n"
        "severity: medium\n"
        "status: open\n"
        "title: W2 test record\n"
        "---\n"
        "\nBody\n",
        encoding="utf-8",
    )


def _without_last_built(payload: dict) -> dict:
    clone = dict(payload)
    clone.pop("last_built", None)
    return clone


def test_scan_index_rebuild_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    _write_record(tmp_path)
    scan_index = _load_scan_index()

    assert scan_index.main(["rebuild", "--project", "install"]) == 0
    files_path = tmp_path / ".agents" / "memory" / "projects" / "install" / "_index" / "files.json"
    first = json.loads(files_path.read_text(encoding="utf-8"))

    assert scan_index.main(["rebuild", "--project", "install"]) == 0
    second = json.loads(files_path.read_text(encoding="utf-8"))

    assert _without_last_built(first) == _without_last_built(second)
    assert first["files"][0]["path"] == "finding/one.md"


def test_install_flow_refreshes_memory_kb_index_when_present() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    assert "SCAN_INDEX_SCRIPT" in text
    assert "refresh_memory_kb_index" in text
    assert '"$SCAN_INDEX_SCRIPT" rebuild --project "$PROJECT"' in text
