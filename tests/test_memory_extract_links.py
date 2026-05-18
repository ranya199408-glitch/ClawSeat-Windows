"""Tests for the typed-link / backlink graph extraction (P1 memory-graph)."""
from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_EXTRACT = _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "extract_links.py"
_QUERY = _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "query_memory.py"
_SPEC = importlib.util.spec_from_file_location("extract_links_under_test", _EXTRACT)
assert _SPEC is not None and _SPEC.loader is not None
extract_links = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(extract_links)


def _run(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _make_page(memory_root: Path, *, project: str, kind: str, name: str, body: str) -> Path:
    page_dir = memory_root / "projects" / project / kind
    page_dir.mkdir(parents=True, exist_ok=True)
    page = page_dir / f"{name}.md"
    page.write_text(body, encoding="utf-8")
    return page


def test_extract_basic_entities(tmp_path: Path) -> None:
    page = _make_page(
        tmp_path,
        project="arena",
        kind="decision",
        name="d1",
        body=(
            "Looking at ARENA-228 we landed commit 318de65bb in "
            "src/views/Home/v3/HomeViewV3.tsx — see [KEY: 边界]. "
            "Also https://github.com/KaneOrca/ClawSeat for context. "
            "BitmaskPhysics and PretextLayer are involved."
        ),
    )
    rc, out, _err = _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path))
    assert rc == 0, out
    summary = json.loads(out)
    assert summary["source"] == "projects/arena/decision/d1"
    targets = set(summary["targets_added"])
    assert "entity:taskid:ARENA-228" in targets
    assert "entity:commit:318de65bb" in targets
    assert "entity:file:src/views/Home/v3/HomeViewV3.tsx" in targets
    assert "entity:key:边界" in targets
    assert "entity:url:https://github.com/KaneOrca/ClawSeat" in targets
    assert "entity:component:BitmaskPhysics" in targets
    assert "entity:component:PretextLayer" in targets


def test_idempotent_rerun(tmp_path: Path) -> None:
    page = _make_page(
        tmp_path,
        project="arena",
        kind="decision",
        name="i1",
        body="ARENA-228 + commit 318de65 + src/foo.tsx",
    )
    rc1, _o1, _ = _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path), "--quiet")
    rc2, _o2, _ = _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path), "--quiet")
    assert rc1 == 0
    assert rc2 == 0

    links_file = tmp_path / "_links" / "projects__arena__decision__i1.jsonl"
    assert links_file.is_file()
    edges = [json.loads(line) for line in links_file.read_text().splitlines() if line]
    assert len(edges) == 3  # ARENA-228 + 318de65 + src/foo.tsx

    backlinks_file = tmp_path / "_backlinks" / "entity++taskid++ARENA-228.jsonl"
    backlink_lines = [
        line for line in backlinks_file.read_text().splitlines() if line
    ]
    assert len(backlink_lines) == 1  # one source, one entry — never duplicated


def test_edge_removal_when_source_changes(tmp_path: Path) -> None:
    page = _make_page(
        tmp_path,
        project="arena",
        kind="decision",
        name="r1",
        body="ARENA-228 mentioned",
    )
    _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path), "--quiet")
    backlink = tmp_path / "_backlinks" / "entity++taskid++ARENA-228.jsonl"
    assert backlink.is_file()

    # Rewrite source: drop ARENA-228, add ARENA-999
    page.write_text("ARENA-999 only", encoding="utf-8")
    rc, out, _ = _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path))
    assert rc == 0
    summary = json.loads(out)
    assert "entity:taskid:ARENA-228" in summary["targets_removed"]
    assert "entity:taskid:ARENA-999" in summary["targets_added"]
    assert not backlink.exists(), "stale backlink file should be cleaned up"
    new_backlink = tmp_path / "_backlinks" / "entity++taskid++ARENA-999.jsonl"
    assert new_backlink.is_file()


def test_query_backlinks_command(tmp_path: Path) -> None:
    p1 = _make_page(tmp_path, project="arena", kind="decision", name="q1", body="ARENA-228")
    p2 = _make_page(tmp_path, project="arena", kind="finding", name="q2", body="ARENA-228 again")
    for page in (p1, p2):
        _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path), "--quiet")

    rc, out, _ = _run(
        str(_QUERY),
        "--memory-dir",
        str(tmp_path),
        "--backlinks",
        "entity:taskid:ARENA-228",
    )
    assert rc == 0
    payload = json.loads(out)
    assert payload["target"] == "entity:taskid:ARENA-228"
    assert payload["incoming_count"] == 2
    sources = {item["from"] for item in payload["incoming"]}
    assert sources == {"projects/arena/decision/q1", "projects/arena/finding/q2"}


def test_query_graph_bfs_depth_2(tmp_path: Path) -> None:
    page = _make_page(
        tmp_path,
        project="arena",
        kind="decision",
        name="g1",
        body="ARENA-228 + commit 318de65 + BitmaskPhysics",
    )
    _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path), "--quiet")

    rc, out, _ = _run(
        str(_QUERY),
        "--memory-dir",
        str(tmp_path),
        "--graph",
        "projects/arena/decision/g1",
        "--depth",
        "2",
    )
    assert rc == 0
    payload = json.loads(out)
    assert payload["root"] == "projects/arena/decision/g1"
    assert payload["depth"] == 2
    assert payload["edge_count"] == 3
    nodes = set(payload["nodes"])
    assert "projects/arena/decision/g1" in nodes
    assert "entity:taskid:ARENA-228" in nodes
    assert "entity:commit:318de65" in nodes
    assert "entity:component:BitmaskPhysics" in nodes


def test_slug_normalization_accepts_md_extension(tmp_path: Path) -> None:
    page = _make_page(tmp_path, project="arena", kind="decision", name="n1", body="ARENA-228")
    _run(str(_EXTRACT), "--file", str(page), "--memory-dir", str(tmp_path), "--quiet")

    # Same slug with .md extension should resolve to the same backlinks file
    rc1, out1, _ = _run(
        str(_QUERY),
        "--memory-dir",
        str(tmp_path),
        "--graph",
        "projects/arena/decision/n1.md",
    )
    rc2, out2, _ = _run(
        str(_QUERY),
        "--memory-dir",
        str(tmp_path),
        "--graph",
        "projects/arena/decision/n1",
    )
    assert rc1 == 0 and rc2 == 0
    p1 = json.loads(out1)
    p2 = json.loads(out2)
    assert p1["root"] == p2["root"]
    assert p1["edge_count"] == p2["edge_count"]


def test_outside_memory_root_returns_error(tmp_path: Path) -> None:
    other = tmp_path / "outside"
    other.mkdir()
    rogue = other / "rogue.md"
    rogue.write_text("ARENA-228", encoding="utf-8")
    rc, _out, err = _run(
        str(_EXTRACT),
        "--file",
        str(rogue),
        "--memory-dir",
        str(tmp_path / "memroot"),
    )
    assert rc == 2
    assert "memory root" in err


def test_naked_hash_not_misidentified_as_commit() -> None:
    text = "abc1234 API key starts with hex and abc1234ef is another"
    edges = extract_links.extract_edges("test.md", text)
    commit_edges = [e for e in edges if e["edge_type"] == "references-commit"]
    assert not commit_edges, f"FP: naked hex hash identified as commit: {commit_edges}"


def test_component_pattern_config_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-project component-patterns.toml overrides default suffixes."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_config_dir = tmp_path / ".agents" / "memory" / "projects" / "test-proj"
    project_config_dir.mkdir(parents=True)
    (project_config_dir / "component-patterns.toml").write_text(
        '[component_patterns]\nsuffixes = ["WidgetSeat"]\n',
        encoding="utf-8",
    )

    suffixes = extract_links._load_component_suffixes(project="test-proj")
    assert suffixes == ["WidgetSeat"]
    edges = extract_links.extract_edges(
        "projects/test-proj/decision/page",
        "MyWidgetSeat is initialized here",
        project="test-proj",
    )
    comp_edges = [e for e in edges if e["edge_type"] == "references-component"]
    assert any(e["target"] == "entity:component:MyWidgetSeat" for e in comp_edges)


def test_code_blocks_skipped() -> None:
    """File paths inside code blocks are not extracted as edges."""
    text = (
        "Normal text here.\n"
        "```python\n"
        "from foo.bar.baz import thing\n"
        "import os.path\n"
        "```\n"
        "More text."
    )
    edges = extract_links.extract_edges("page.md", text)
    file_edges = [e for e in edges if e["edge_type"] == "references-file"]
    targets = [e.get("target", "") for e in file_edges]
    assert not any("foo.bar" in t or "os.path" in t for t in targets), (
        f"FP: code block contents extracted as file edges: {targets}"
    )


def test_edge_dedup_per_source_target() -> None:
    """Multiple mentions of same target produce only one edge."""
    text = "TASK-123 mentioned here. Also TASK-123 again. And TASK-123 once more."
    edges = extract_links.extract_edges("page.md", text)
    task_edges = [e for e in edges if "TASK-123" in str(e.get("target", ""))]
    assert len(task_edges) == 1, f"Expected 1 edge, got {len(task_edges)}: {task_edges}"
