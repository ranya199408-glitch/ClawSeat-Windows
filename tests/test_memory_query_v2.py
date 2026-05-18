"""Tests for query_memory.py v2 — new layout filters + backward compat.

Coverage:
  - --project + --kind lists facts from projects/<p>/decisions/ etc.
  - --project + --kind + --since filters by ts
  - --project only lists all kinds in a project
  - --kind only scans all projects
  - --since only scans all projects (smoke)
  - Empty result exits 1, results exit 0
  - --key backward compat reads machine/<name>.json first
  - --key backward compat falls back to flat <name>.json
  - --search searches machine/ dir (new layout)
  - --status shows machine_files list
  - --file reads from machine/ first
  - _shared project routes to shared/ subtree
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "skills" / "memory-oracle" / "scripts"
_QUERY_PY = _SCRIPTS / "query_memory.py"
sys.path.insert(0, str(_SCRIPTS))

import subprocess


# ── Fixture helpers ───────────────────────────────────────────────────────────


def run_query(*args: str, memory_dir: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_QUERY_PY), "--memory-dir", memory_dir] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def write_fact(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def make_fact(
    kind: str,
    project: str,
    *,
    ts: str = "2026-04-18T10:00:00+00:00",
    title: str = "Test",
    fact_id: str | None = None,
) -> dict:
    if fact_id is None:
        fact_id = f"{kind}-{project}-testid1"
    return {
        "schema_version": 1,
        "kind": kind,
        "id": fact_id,
        "project": project,
        "author": "planner",
        "ts": ts,
        "title": title,
        "body": "",
        "related_task_ids": [],
        "evidence": [],
        "supersedes": None,
        "confidence": "medium",
        "source": "write_api",
    }


@pytest.fixture()
def memory_tree(tmp_path):
    """Set up a v3 memory tree with a few facts and machine/ files."""
    # machine/ files
    machine = tmp_path / "machine"
    machine.mkdir()
    creds = {"scanned_at": "2026-04-18T10:00:00+00:00", "keys": {"ANTHROPIC_API_KEY": {"value": "<API_KEY>"}}}
    (machine / "credentials.json").write_text(json.dumps(creds))
    github = {"scanned_at": "2026-04-18T10:00:00+00:00", "gh_cli": {"active_login": "testuser"}}
    (machine / "github.json").write_text(json.dumps(github))
    ctx = {"last_refresh_ts": "2026-04-18T10:00:00+00:00", "current_project": "install"}
    (machine / "current_context.json").write_text(json.dumps(ctx))

    # projects/install/decisions/
    d1 = make_fact("decision", "install", ts="2026-04-18T10:00:00+00:00", title="Decision A", fact_id="decision-install-aaaa0001")
    d2 = make_fact("decision", "install", ts="2026-04-20T10:00:00+00:00", title="Decision B", fact_id="decision-install-bbbb0002")
    write_fact(tmp_path / "projects" / "install" / "decisions" / "decision-install-aaaa0001.json", d1)
    write_fact(tmp_path / "projects" / "install" / "decisions" / "decision-install-bbbb0002.json", d2)

    # projects/install/deliveries/
    del1 = make_fact("delivery", "install", ts="2026-04-19T10:00:00+00:00", title="Delivery X", fact_id="delivery-install-cccc0003")
    write_fact(tmp_path / "projects" / "install" / "deliveries" / "delivery-install-cccc0003.json", del1)

    # projects/install/findings/
    f1 = make_fact("finding", "install", ts="2026-04-17T10:00:00+00:00", title="Finding F", fact_id="finding-install-dddd0004")
    write_fact(tmp_path / "projects" / "install" / "findings" / "finding-install-dddd0004.json", f1)

    # projects/other/decisions/
    d3 = make_fact("decision", "other", ts="2026-04-16T10:00:00+00:00", title="Other Decision", fact_id="decision-other-eeee0005")
    write_fact(tmp_path / "projects" / "other" / "decisions" / "decision-other-eeee0005.json", d3)

    # shared/library_knowledge/
    lk = {
        "schema_version": 1, "kind": "library_knowledge", "id": "library_knowledge-shared-ffff0006",
        "project": "_shared", "author": "memory", "ts": "2026-04-18T12:00:00+00:00",
        "title": "pytest tips", "body": "", "related_task_ids": [], "evidence": [
            {"type": "url", "value": "https://docs.pytest.org", "trust": "high", "source_url": "https://docs.pytest.org"}
        ], "supersedes": None, "confidence": "high", "source": "research",
    }
    write_fact(tmp_path / "shared" / "library_knowledge" / "library_knowledge-shared-ffff0006.json", lk)

    return tmp_path


# ── v3 list mode: --project + --kind ─────────────────────────────────────────


def test_project_and_kind_lists_decisions(memory_tree):
    result = run_query("--project", "install", "--kind", "decision", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 2
    titles = {f["title"] for f in facts}
    assert "Decision A" in titles
    assert "Decision B" in titles


def test_project_and_kind_lists_deliveries(memory_tree):
    result = run_query("--project", "install", "--kind", "delivery", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 1
    assert facts[0]["title"] == "Delivery X"


def test_project_and_kind_lists_findings(memory_tree):
    result = run_query("--project", "install", "--kind", "finding", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 1
    assert facts[0]["title"] == "Finding F"


def test_no_facts_in_empty_kind_exits_1(memory_tree):
    result = run_query("--project", "install", "--kind", "issue", memory_dir=str(memory_tree))
    assert result.returncode == 1
    assert json.loads(result.stdout) == []


def test_unknown_project_exits_1(memory_tree):
    result = run_query("--project", "nonexistent", "--kind", "decision", memory_dir=str(memory_tree))
    assert result.returncode == 1


# ── v3 list mode: --since filter ─────────────────────────────────────────────


def test_since_filter_excludes_old_decisions(memory_tree):
    result = run_query(
        "--project", "install", "--kind", "decision",
        "--since", "2026-04-19",
        memory_dir=str(memory_tree),
    )
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 1
    assert facts[0]["title"] == "Decision B"  # ts 2026-04-20


def test_since_filter_includes_exact_date(memory_tree):
    result = run_query(
        "--project", "install", "--kind", "decision",
        "--since", "2026-04-18",
        memory_dir=str(memory_tree),
    )
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 2  # both 2026-04-18 and 2026-04-20


def test_since_filter_excludes_all_exits_1(memory_tree):
    result = run_query(
        "--project", "install", "--kind", "decision",
        "--since", "2026-04-30",
        memory_dir=str(memory_tree),
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == []


# ── v3 list mode: --project only ─────────────────────────────────────────────


def test_project_only_lists_all_kinds(memory_tree):
    result = run_query("--project", "install", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    kinds = {f["kind"] for f in facts}
    assert "decision" in kinds
    assert "delivery" in kinds
    assert "finding" in kinds


# ── v3 list mode: --kind only (across all projects) ──────────────────────────


def test_kind_only_lists_across_all_projects(memory_tree):
    result = run_query("--kind", "decision", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    projects = {f["project"] for f in facts}
    assert "install" in projects
    assert "other" in projects


def test_kind_library_knowledge_searches_shared(memory_tree):
    result = run_query("--kind", "library_knowledge", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 1
    assert facts[0]["title"] == "pytest tips"


# ── v3 list mode: _shared project ────────────────────────────────────────────


def test_shared_project_lists_library_knowledge(memory_tree):
    result = run_query("--project", "_shared", "--kind", "library_knowledge", memory_dir=str(memory_tree))
    assert result.returncode == 0
    facts = json.loads(result.stdout)
    assert len(facts) == 1
    assert facts[0]["project"] == "_shared"


# ── --key backward compat: reads machine/ first ───────────────────────────────


def test_key_reads_from_machine_subdir(memory_tree):
    result = run_query("--key", "credentials.keys.ANTHROPIC_API_KEY.value", memory_dir=str(memory_tree))
    assert result.returncode == 0
    assert "<API_KEY>" in result.stdout


def test_key_reads_github_from_machine(memory_tree):
    result = run_query("--key", "github.gh_cli.active_login", memory_dir=str(memory_tree))
    assert result.returncode == 0
    assert "testuser" in result.stdout


def test_key_falls_back_to_flat_layout(tmp_path):
    # No machine/ dir — only flat layout
    flat_data = {"answer": "from-flat"}
    (tmp_path / "myfile.json").write_text(json.dumps(flat_data))
    result = run_query("--key", "myfile.answer", memory_dir=str(tmp_path))
    assert result.returncode == 0
    assert "from-flat" in result.stdout


def test_key_prefers_machine_over_flat(tmp_path):
    machine = tmp_path / "machine"
    machine.mkdir()
    (machine / "credentials.json").write_text(json.dumps({"source": "machine"}))
    (tmp_path / "credentials.json").write_text(json.dumps({"source": "flat"}))
    result = run_query("--key", "credentials.source", memory_dir=str(tmp_path))
    assert result.returncode == 0
    assert "machine" in result.stdout


def test_key_missing_file_exits_1(memory_tree):
    result = run_query("--key", "nonexistent.foo.bar", memory_dir=str(memory_tree))
    assert result.returncode == 1


def test_key_missing_nested_path_exits_1(memory_tree):
    result = run_query("--key", "credentials.keys.NONEXISTENT_KEY", memory_dir=str(memory_tree))
    assert result.returncode == 1


# ── --search searches machine/ layout ────────────────────────────────────────


def test_search_finds_value_in_machine_dir(memory_tree):
    result = run_query("--search", "testuser", memory_dir=str(memory_tree))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["count"] >= 1
    assert any("machine/" in m["file"] for m in out["matches"])


def test_search_finds_key_in_machine_credentials(memory_tree):
    result = run_query("--search", "ANTHROPIC_API_KEY", memory_dir=str(memory_tree))
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert out["count"] >= 1


def test_search_no_match_exits_1(memory_tree):
    result = run_query("--search", "zzz_no_such_term_zzz", memory_dir=str(memory_tree))
    assert result.returncode == 1


# ── --file reads from machine/ ────────────────────────────────────────────────


def test_file_reads_from_machine_subdir(memory_tree):
    result = run_query("--file", "credentials", memory_dir=str(memory_tree))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "keys" in data


def test_file_with_section(memory_tree):
    result = run_query("--file", "github", "--section", "gh_cli", memory_dir=str(memory_tree))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data.get("active_login") == "testuser"


# ── --status shows machine_files ─────────────────────────────────────────────


def test_status_shows_machine_files(memory_tree):
    result = run_query("--status", memory_dir=str(memory_tree))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "machine_files" in data
    assert "credentials.json" in data["machine_files"]
    assert "github.json" in data["machine_files"]


def test_status_shows_projects(memory_tree):
    result = run_query("--status", memory_dir=str(memory_tree))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "projects" in data
    assert "install" in data["projects"]


# ── No args prints usage ──────────────────────────────────────────────────────


def test_no_args_exits_2(memory_tree):
    result = run_query(memory_dir=str(memory_tree))
    assert result.returncode == 2


# ── F1: reflection and event JSONL routing (reviewer finding) ─────────────────


@pytest.fixture()
def memory_with_jsonl(tmp_path):
    """Tree with reflections.jsonl and events.log JSONL files."""
    # projects/install/reflections.jsonl — two records
    proj = tmp_path / "projects" / "install"
    proj.mkdir(parents=True)
    r1 = {"schema_version": 1, "kind": "reflection", "id": "r1", "project": "install",
          "ts": "2026-04-18T10:00:00+00:00", "title": "Reflection 1"}
    r2 = {"schema_version": 1, "kind": "reflection", "id": "r2", "project": "install",
          "ts": "2026-04-20T10:00:00+00:00", "title": "Reflection 2"}
    (proj / "reflections.jsonl").write_text(
        json.dumps(r1) + "\n" + json.dumps(r2) + "\n", encoding="utf-8"
    )

    # projects/other/reflections.jsonl — one record
    other = tmp_path / "projects" / "other"
    other.mkdir(parents=True)
    r3 = {"schema_version": 1, "kind": "reflection", "id": "r3", "project": "other",
          "ts": "2026-04-19T10:00:00+00:00", "title": "Other Reflection"}
    (other / "reflections.jsonl").write_text(json.dumps(r3) + "\n", encoding="utf-8")

    # events.log — global JSONL
    e1 = {"kind": "event", "id": "e1", "ts": "2026-04-18T09:00:00+00:00", "title": "Event A"}
    e2 = {"kind": "event", "id": "e2", "ts": "2026-04-19T09:00:00+00:00", "title": "Event B"}
    (tmp_path / "events.log").write_text(
        json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_kind_reflection_project_reads_jsonl(memory_with_jsonl):
    result = run_query("--project", "install", "--kind", "reflection",
                       memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    assert len(records) == 2
    titles = {r["title"] for r in records}
    assert "Reflection 1" in titles
    assert "Reflection 2" in titles


def test_kind_reflection_all_projects(memory_with_jsonl):
    result = run_query("--kind", "reflection", memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    assert len(records) == 3
    projects = {r["project"] for r in records}
    assert "install" in projects
    assert "other" in projects


def test_kind_reflection_since_filter(memory_with_jsonl):
    result = run_query("--project", "install", "--kind", "reflection",
                       "--since", "2026-04-19",
                       memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    assert len(records) == 1
    assert records[0]["title"] == "Reflection 2"


def test_kind_event_reads_global_log(memory_with_jsonl):
    result = run_query("--kind", "event", memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    assert len(records) == 2
    titles = {r["title"] for r in records}
    assert "Event A" in titles
    assert "Event B" in titles


def test_kind_event_project_ignored_still_reads_global_log(memory_with_jsonl):
    # For event kind, project is ignored — events.log is always global
    result = run_query("--project", "install", "--kind", "event",
                       memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    assert len(records) == 2


def test_kind_event_since_filter(memory_with_jsonl):
    result = run_query("--kind", "event", "--since", "2026-04-19",
                       memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    assert len(records) == 1
    assert records[0]["title"] == "Event B"


def test_empty_reflections_exits_1(memory_with_jsonl):
    # project with no reflections.jsonl
    (memory_with_jsonl / "projects" / "empty-proj").mkdir(parents=True)
    result = run_query("--project", "empty-proj", "--kind", "reflection",
                       memory_dir=str(memory_with_jsonl))
    assert result.returncode == 1
    assert json.loads(result.stdout) == []


def test_empty_events_log_exits_1(tmp_path):
    result = run_query("--kind", "event", memory_dir=str(tmp_path))
    assert result.returncode == 1
    assert json.loads(result.stdout) == []


def test_project_only_includes_reflections(memory_with_jsonl):
    result = run_query("--project", "install", memory_dir=str(memory_with_jsonl))
    assert result.returncode == 0
    records = json.loads(result.stdout)
    kinds = {r["kind"] for r in records}
    assert "reflection" in kinds
