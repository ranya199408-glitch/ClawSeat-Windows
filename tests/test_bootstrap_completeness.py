"""C7 tests: bootstrap-completeness checker.

The P1 ask from the hardening list:

    planner brief / bootstrap 完整性检查 — 像这次 cartooner 缺
    PLANNER_BRIEF.md 这种情况，应该在 bootstrap 阶段直接发现，
    而不是运行中才暴露。

This suite locks: the checker produces the right severity for each
missing artefact, knows whether a `planner` seat is actually declared,
and surfaces the PROJECT_BINDING.toml (C2) absence as a warning.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))

from bootstrap_completeness import evaluate_profile  # noqa: E402


def _make_profile(
    tmp_path: Path,
    *,
    project_name: str = "install",
    seats: list[str] | None = None,
    planner_brief_path: Path | None = None,
    send_script: Path | None = None,
) -> SimpleNamespace:
    tasks_root = tmp_path / "tasks" / project_name
    tasks_root.mkdir(parents=True, exist_ok=True)
    (tmp_path / "repo").mkdir(exist_ok=True)
    script = send_script if send_script is not None else tmp_path / "send-and-verify.sh"
    if send_script is None and not script.exists():
        script.write_text("#!/bin/bash\n")
        script.chmod(0o755)
    return SimpleNamespace(
        profile_name="test",
        project_name=project_name,
        tasks_root=tasks_root,
        project_doc=tasks_root / "PROJECT.md",
        tasks_doc=tasks_root / "TASKS.md",
        status_doc=tasks_root / "STATUS.md",
        send_script=script,
        repo_root=tmp_path / "repo",
        seats=seats if seats is not None else ["koder", "planner", "builder-1"],
        runtime_seats=None,
        heartbeat_owner="koder",
        heartbeat_transport="openclaw",
        planner_brief_path=planner_brief_path,
    )


def _find(report, check: str):
    items = [i for i in report.items if i.check == check]
    assert len(items) == 1, f"expected exactly one item for {check!r}, got {len(items)}"
    return items[0]


# ── tasks_root ────────────────────────────────────────────────────────


def test_tasks_root_missing_is_error(tmp_path):
    profile = _make_profile(tmp_path)
    # Nuke tasks_root after profile creation.
    import shutil
    shutil.rmtree(profile.tasks_root)
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    assert _find(report, "tasks_root").severity == "error"
    assert report.has_errors


# ── canonical docs ────────────────────────────────────────────────────


def test_missing_docs_are_warnings(tmp_path):
    profile = _make_profile(tmp_path)
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    # tasks_root exists, parent is writable → missing docs = warnings.
    for name in ("project_doc", "tasks_doc", "status_doc"):
        assert _find(report, name).severity == "warning"
    assert report.has_warnings and not report.has_errors


def test_present_docs_are_ok(tmp_path):
    profile = _make_profile(tmp_path)
    profile.project_doc.write_text("# PROJECT")
    profile.tasks_doc.write_text("# TASKS")
    profile.status_doc.write_text("# STATUS")
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    for name in ("project_doc", "tasks_doc", "status_doc"):
        assert _find(report, name).severity == "ok"


# ── send_script ───────────────────────────────────────────────────────


def test_send_script_missing_is_error(tmp_path):
    missing = tmp_path / "does-not-exist.sh"
    profile = _make_profile(tmp_path, send_script=missing)
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    assert _find(report, "send_script").severity == "error"


def test_send_script_not_executable_is_error(tmp_path):
    non_exec = tmp_path / "transport.sh"
    non_exec.write_text("#!/bin/bash\n")
    non_exec.chmod(0o644)
    profile = _make_profile(tmp_path, send_script=non_exec)
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    assert _find(report, "send_script").severity == "error"


# ── planner_brief ─────────────────────────────────────────────────────


def test_planner_seat_missing_brief_is_warning(tmp_path):
    profile = _make_profile(tmp_path, seats=["koder", "planner"])
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    item = _find(report, "planner_brief")
    assert item.severity == "warning"
    assert "PLANNER_BRIEF" in item.detail or "planner" in item.detail.lower()


def test_planner_brief_present_is_ok(tmp_path):
    planner_dir = tmp_path / "tasks" / "install" / "planner"
    planner_dir.mkdir(parents=True)
    brief = planner_dir / "PLANNER_BRIEF.md"
    brief.write_text("# brief\n")
    profile = _make_profile(
        tmp_path, seats=["koder", "planner"], planner_brief_path=brief,
    )
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    assert _find(report, "planner_brief").severity == "ok"


def test_no_planner_seat_brief_is_info(tmp_path):
    profile = _make_profile(tmp_path, seats=["koder"])
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    assert _find(report, "planner_brief").severity == "info"


# ── PROJECT_BINDING.toml (C2 tie-in) ──────────────────────────────────


def test_project_binding_missing_is_warning(tmp_path):
    profile = _make_profile(tmp_path)
    bindings_root = tmp_path / "bindings"
    bindings_root.mkdir()
    report = evaluate_profile(profile, bindings_root=bindings_root)
    item = _find(report, "project_binding")
    assert item.severity == "warning"
    assert "project bind" in item.fix


def test_project_binding_present_is_ok(tmp_path):
    profile = _make_profile(tmp_path)
    bindings_root = tmp_path / "bindings"
    (bindings_root / "install").mkdir(parents=True)
    (bindings_root / "install" / "PROJECT_BINDING.toml").write_text(
        'project = "install"\nfeishu_group_id = "<FEISHU_GROUP_ID>"\n'
    )
    report = evaluate_profile(profile, bindings_root=bindings_root)
    assert _find(report, "project_binding").severity == "ok"


# ── report rendering ──────────────────────────────────────────────────


def test_render_green_when_everything_ok(tmp_path):
    profile = _make_profile(tmp_path, seats=["koder"])  # no planner -> info
    profile.project_doc.write_text("# PROJECT")
    profile.tasks_doc.write_text("# TASKS")
    profile.status_doc.write_text("# STATUS")
    bindings_root = tmp_path / "bindings"
    (bindings_root / "install").mkdir(parents=True)
    (bindings_root / "install" / "PROJECT_BINDING.toml").write_text(
        'project = "install"\nfeishu_group_id = "<FEISHU_GROUP_ID>"\n'
    )
    report = evaluate_profile(profile, bindings_root=bindings_root)
    assert not report.has_errors and not report.has_warnings
    assert "result: green" in report.render()


def test_render_yellow_when_warnings_only(tmp_path):
    profile = _make_profile(tmp_path)
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    rendered = report.render()
    assert "result: yellow" in rendered
    assert "[WARN]" in rendered


def test_render_red_when_errors(tmp_path):
    profile = _make_profile(tmp_path)
    import shutil
    shutil.rmtree(profile.tasks_root)
    report = evaluate_profile(profile, bindings_root=tmp_path / "bindings")
    rendered = report.render()
    assert "result: red" in rendered
    assert "[FAIL]" in rendered
