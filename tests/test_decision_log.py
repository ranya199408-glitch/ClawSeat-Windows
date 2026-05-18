from __future__ import annotations

import importlib.util
import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "skills" / "clawseat-intake" / "scripts" / "decision-log.py"


def _load_decision_log():
    spec = importlib.util.spec_from_file_location("decision_log", _SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_append_creates_dir_and_markdown_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    decision_log = _load_decision_log()

    record = decision_log.append_decision(
        "install",
        "task-1",
        "Dispatch builder",
        "Implementation lane is the fastest path.",
    )

    decision_dir = tmp_path / ".agents" / "memory" / "projects" / "install" / "decision"
    files = list(decision_dir.glob("*.md"))
    assert len(files) == 1
    assert files[0].name.endswith("-dispatch-builder.md")
    assert "Implementation lane is the fastest path." in files[0].read_text(encoding="utf-8")
    assert record["kind"] == "decision"


def test_append_frontmatter_has_required_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    decision_log = _load_decision_log()

    record = decision_log.append_decision(
        "install",
        "task-2",
        "Record dispatch",
        "Planner selected builder.",
        seat="memory",
        decision_type="dispatch",
    )
    path = decision_log._decision_record_path("install", record["ts"], record["title"])
    parsed = decision_log._parse_frontmatter(path)

    for field in (
        "issue_id",
        "ts",
        "task_id",
        "project",
        "seat",
        "kind",
        "title",
        "status",
        "detail",
        "decision_type",
        "auto_mode",
        "reason",
    ):
        assert field in parsed
    assert re.fullmatch(r"[0-9a-f-]{36}", parsed["issue_id"])
    assert parsed["auto_mode"] is True
    assert parsed["status"] == "open"


def test_list_decisions_reads_markdown_sorted_with_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    decision_log = _load_decision_log()
    decision_dir = tmp_path / ".agents" / "memory" / "projects" / "install" / "decision"
    decision_dir.mkdir(parents=True)

    for ts, title in (
        ("2026-04-27T08:43:00Z", "third"),
        ("2026-04-27T08:41:00Z", "first"),
        ("2026-04-27T08:42:00Z", "second"),
    ):
        record = {
            "issue_id": f"id-{title}",
            "ts": ts,
            "task_id": f"task-{title}",
            "project": "install",
            "seat": "planner",
            "kind": "decision",
            "title": title,
            "status": "open",
            "detail": title,
            "decision_type": "auto",
            "auto_mode": True,
            "reason": title,
            "body": title,
        }
        decision_log._decision_record_path("install", ts, title).write_text(
            decision_log._render_md(record),
            encoding="utf-8",
        )

    records = decision_log.list_decisions("install", limit=2)
    assert [record["title"] for record in records] == ["second", "third"]


def test_slug_filename_generation_handles_cjk_title(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    decision_log = _load_decision_log()

    path = decision_log._decision_record_path("install", "2026-04-27T08:41:00Z", "派工 M2.0-C reporting")

    assert path.name == "2026-04-27T08-41-00Z-m2-0-c-reporting.md"


def test_frontmatter_parse_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    decision_log = _load_decision_log()
    record = {
        "issue_id": "00000000-0000-0000-0000-000000000000",
        "ts": "2026-04-27T08:41:00Z",
        "task_id": "task-roundtrip",
        "project": "install",
        "seat": "planner",
        "kind": "decision",
        "title": "Title: needs quoting",
        "status": "open",
        "detail": "Detail with # hash",
        "decision_type": "dispatch",
        "auto_mode": False,
        "reason": "Operator requested it.",
        "body": "Markdown body",
    }
    path = tmp_path / "roundtrip.md"
    path.write_text(decision_log._render_md(record), encoding="utf-8")

    parsed = decision_log._parse_frontmatter(path)
    assert parsed["title"] == "Title: needs quoting"
    assert parsed["detail"] == "Detail with # hash"
    assert parsed["auto_mode"] is False
