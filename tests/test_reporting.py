from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "skills" / "clawseat-intake" / "scripts" / "reporting.py"


def _load_reporting():
    spec = importlib.util.spec_from_file_location("reporting", _SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_projects_json(home: Path) -> None:
    path = home / ".clawseat" / "projects.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "projects": {
                    "install": {"status": "active"},
                    "cartooner": {"status": "archived"},
                    "openclaw": {},
                },
            }
        ),
        encoding="utf-8",
    )


def _write_decision_md(home: Path, project: str, record: dict) -> None:
    path = (
        home
        / ".agents"
        / "memory"
        / "projects"
        / project
        / "decision"
        / f"{record['ts'].replace(':', '-')}-{record['title']}.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = "\n".join(f"{key}: {value}" for key, value in record.items())
    path.write_text(f"---\n{frontmatter}\n---\n\nbody\n", encoding="utf-8")


def test_load_all_projects_reads_projects_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_projects_json(tmp_path)
    reporting = _load_reporting()

    assert reporting.load_all_projects() == ["install", "openclaw"]


def test_load_decisions_returns_records(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_decision_md(
        tmp_path,
        "install",
        {"ts": "2026-04-01T00:00:00Z", "project": "install", "seat": "planner", "title": "old"},
    )
    _write_decision_md(
        tmp_path,
        "install",
        {"ts": "2026-04-27T08:41:00Z", "project": "install", "seat": "planner", "title": "new"},
    )
    reporting = _load_reporting()

    records = reporting.load_decisions("install", since="2026-04-02", limit=10)
    assert [record["title"] for record in records] == ["new"]


def test_load_decisions_missing_file_returns_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    reporting = _load_reporting()

    assert reporting.load_decisions("install") == []


def test_aggregate_sorts_by_ts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_decision_md(
        tmp_path,
        "install",
        {"ts": "2026-04-27T08:42:00Z", "project": "install", "seat": "planner", "title": "second"},
    )
    _write_decision_md(
        tmp_path,
        "cartooner",
        {"ts": "2026-04-27T08:41:00Z", "project": "cartooner", "seat": "planner", "title": "first"},
    )
    reporting = _load_reporting()

    records = reporting.aggregate(["install", "cartooner"])
    assert [record["title"] for record in records] == ["first", "second"]


def test_format_summary_card_contains_project_name() -> None:
    reporting = _load_reporting()

    card = reporting.format_summary_card(
        [
            {
                "ts": "2026-04-27T08:41:00Z",
                "project": "install",
                "seat": "planner",
                "title": "派工 M2.0-C reporting",
            }
        ]
    )

    assert "## install (1 条)" in card
    assert "- 2026-04-27T08:41:00Z [planner] 派工 M2.0-C reporting" in card
