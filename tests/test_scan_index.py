from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "scan_index.py"


def _load_scan_index():
    spec = importlib.util.spec_from_file_location("scan_index", _SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_record(home: Path, project: str, relative: str, **fields: str) -> Path:
    path = home / ".agents" / "memory" / "projects" / project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = {
        "issue_id": "issue-1",
        "ts": "2026-04-27T08:41:00Z",
        "project": project,
        "seat": "planner",
        "kind": "decision",
        "title": "Record title",
        "status": "open",
    }
    defaults.update(fields)
    frontmatter = "\n".join(f"{key}: {value}" for key, value in defaults.items())
    path.write_text(f"---\n{frontmatter}\n---\n\nBody [[linked-note]]\n", encoding="utf-8")
    return path


def test_parse_frontmatter_valid(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    path = _write_record(tmp_path, "install", "decision/one.md", title="Valid title")
    scan_index = _load_scan_index()

    parsed = scan_index.parse_frontmatter(path)
    assert parsed is not None
    assert parsed["project"] == "install"
    assert parsed["title"] == "Valid title"


def test_parse_frontmatter_no_frontmatter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    path = tmp_path / "plain.md"
    path.write_text("# No frontmatter\n", encoding="utf-8")
    scan_index = _load_scan_index()

    assert scan_index.parse_frontmatter(path) is None


def test_parse_frontmatter_tolerates_shell_backslash_in_quoted_value(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    path = tmp_path / "record.md"
    path.write_text(
        '---\nevidence: "cron.sh: [[ \\"\\$mode\\" == \\"daily\\" ]]"\n---\n\nBody\n',
        encoding="utf-8",
    )
    scan_index = _load_scan_index()

    parsed = scan_index.parse_frontmatter(path)
    assert parsed is not None
    assert parsed["evidence"] == 'cron.sh: [[ \\"\\$mode\\" == \\"daily\\" ]]'


def test_build_files_index_empty_project(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    scan_index = _load_scan_index()

    index = scan_index.build_files_index("install")
    assert index["version"] == 1
    assert index["project"] == "install"
    assert index["files"] == []


def test_build_files_index_with_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    _write_record(tmp_path, "install", "decision/one.md", kind="decision", severity="high")
    _write_record(tmp_path, "install", "qa/two.md", kind="alignment", severity="low")
    scan_index = _load_scan_index()

    index = scan_index.build_files_index("install")
    assert [entry["path"] for entry in index["files"]] == ["decision/one.md", "qa/two.md"]
    assert index["files"][0]["severity"] == "high"


def test_build_timeline_sorted_by_ts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    scan_index = _load_scan_index()
    files = {
        "project": "install",
        "files": [
            {"ts": "2026-04-27T08:42:00Z", "path": "decision/two.md", "kind": "decision"},
            {"ts": "2026-04-27T08:41:00Z", "path": "decision/one.md", "kind": "decision"},
        ],
    }

    timeline = scan_index.build_timeline(files)
    assert [entry["path"] for entry in timeline] == ["decision/one.md", "decision/two.md"]


def test_rebuild_command_writes_all_index_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_HOME", raising=False)
    _write_record(tmp_path, "install", "decision/one.md")
    scan_index = _load_scan_index()

    assert scan_index.main(["rebuild", "--project", "install"]) == 0

    index_dir = tmp_path / ".agents" / "memory" / "projects" / "install" / "_index"
    assert (index_dir / "files.json").is_file()
    assert (index_dir / "search.json").is_file()
    assert (index_dir / "links.json").is_file()
    assert (index_dir / "timeline.jsonl").is_file()
    files = json.loads((index_dir / "files.json").read_text(encoding="utf-8"))
    assert files["files"][0]["path"] == "decision/one.md"
