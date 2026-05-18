"""Smoke coverage for the 16-module agent_admin control plane and the
21-script gstack-harness runtime (audit H5 + H6).

These aren't deep behavioral tests — they're broad CLI/import smoke
that catches `NameError` / `ImportError` / argparse wiring regressions
the second they hit HEAD. Before this file every module under
`core/scripts/agent_admin_*.py` and
`core/skills/gstack-harness/scripts/*.py` was reachable only through
full-stack integration runs that require tmux + real profiles + Feishu.

Each test either:
- imports the module (catches import-time explosions like bad re-exports)
- invokes the CLI with `--help` (catches argparse regressions)
- exercises a pure function with canned inputs (catches the subset of
  logic that doesn't depend on the runtime)

Deep behavioral tests belong in their own files (test_store_list.py,
test_dispatch_task.py, etc.) when specific features are hardened.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_ADMIN = _REPO / "core" / "scripts"
_HARNESS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_MIGRATION = _REPO / "core" / "migration"
for _p in (_ADMIN, _HARNESS, _MIGRATION):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _import_in_subprocess(module_name: str, extra_path: Path) -> subprocess.CompletedProcess[str]:
    """Import *module_name* in a fresh subprocess with *extra_path* on PYTHONPATH.

    Required because sibling tests (e.g. test_tool_binaries_resolution,
    test_openclaw_koder_workspace, test_correlation_id_plumbing) import
    the same admin / harness modules during collection. An in-process
    `importlib.import_module` call would then hit the sys.modules cache
    and silently pass even if the module body had been broken —
    defeating the smoke's whole purpose. We can't use
    `sys.modules.pop(...) + importlib.reload` either because
    test_tool_binaries_resolution.test_runtime_reuses_config_default_path
    relies on the original module object's identity for `DEFAULT_PATH`.
    A clean subprocess is the only way to guarantee the module body
    actually runs while leaving the parent test process state intact.
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(extra_path), str(_REPO)] + ([existing] if existing else [])
    )
    return subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


# ── H5: control-plane module import + help smoke ────────────────────

ADMIN_MODULES = [
    "agent_admin",
    "agent_admin_commands",
    "agent_admin_config",
    "agent_admin_crud",
    "agent_admin_heartbeat",
    "agent_admin_info",
    "agent_admin_parser",
    "agent_admin_resolve",
    "agent_admin_runtime",
    "agent_admin_session",
    "agent_admin_store",
    "agent_admin_switch",
    "agent_admin_template",
    "agent_admin_window",
    "agent_admin_workspace",
    # agent_admin_legacy and agent_admin_tui are imported lazily/only under
    # CLI flags; skip them here to avoid pulling extra deps.
]


@pytest.mark.parametrize("module_name", ADMIN_MODULES)
def test_admin_module_imports_cleanly(module_name: str) -> None:
    """Import must not raise. Catches cross-module symbol breakage
    (the whole reason `agent_admin` was split into 15 focused files in
    the first place).

    Run in a fresh subprocess — see `_import_in_subprocess` docstring
    for the full rationale. Summary: an in-process
    `importlib.import_module` would hit the sys.modules cache populated
    by sibling tests and silently pass even if the module body had been
    broken.
    """
    result = _import_in_subprocess(module_name, _ADMIN)
    assert result.returncode == 0, (
        f"import {module_name} failed:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def test_agent_admin_cli_help_runs() -> None:
    """`python agent_admin.py --help` must exit 0 with the usage block.
    Wires every subparser, so a broken argparse signature anywhere in
    the control plane surfaces here."""
    result = subprocess.run(
        [sys.executable, str(_ADMIN / "agent_admin.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    # Spot-check a handful of top-level commands known to be wired up.
    for expected in ("project", "engineer", "session", "window"):
        assert expected in out, f"subcommand `{expected}` missing from help"


def test_skill_manager_cli_help_runs() -> None:
    result = subprocess.run(
        [sys.executable, str(_ADMIN / "skill_manager.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "check" in result.stdout + result.stderr


def test_agent_admin_config_supported_matrix_complete() -> None:
    """SUPPORTED_RUNTIME_MATRIX must cover every known backend CLI so
    provider validation never accidentally drops one."""
    import agent_admin_config as cfg
    for tool in ("claude", "codex", "gemini"):
        assert tool in cfg.SUPPORTED_RUNTIME_MATRIX, tool
        tool_map = cfg.SUPPORTED_RUNTIME_MATRIX[tool]
        assert "oauth" in tool_map, f"{tool} should support oauth"
        assert tool_map["oauth"], f"{tool} oauth should have at least one provider"


def test_agent_admin_store_load_toml_roundtrip(tmp_path: Path) -> None:
    import agent_admin as aa

    p = tmp_path / "t.toml"
    p.write_text('name = "hello"\nvalue = 42\n', encoding="utf-8")
    data = aa.load_toml(p)
    assert data == {"name": "hello", "value": 42}


def test_agent_admin_workspace_renderers_produce_strings() -> None:
    """Pure text renderers live in agent_admin_workspace. They shouldn't
    crash on empty-engineer fixtures."""
    from agent_admin_workspace import render_role_line

    # render_role_line takes a role+engineer dataclass-ish shape; we
    # feed a minimal object. If signature drifts, this will fail.
    import agent_admin as aa
    engineer = aa.Engineer(
        engineer_id="stub",
        display_name="stub",
        role="builder",
    )
    line = render_role_line(engineer)
    assert isinstance(line, str)
    assert "builder" in line


# ── H6: gstack-harness runtime smoke ────────────────────────────────

HARNESS_SCRIPTS_WITH_HELP = [
    "dispatch_task.py",
    "complete_handoff.py",
    "notify_seat.py",
    "verify_handoff.py",
    "provision_heartbeat.py",
    "send_delegation_report.py",
    "render_console.py",
    "bootstrap_harness.py",
    "ack_contract.py",
    "migrate_profile.py",
    "start_seat.py",
]


@pytest.mark.parametrize("script", HARNESS_SCRIPTS_WITH_HELP)
def test_harness_script_help_runs(script: str) -> None:
    """Every CLI entry point must at least show --help without crashing.
    Catches argparse regressions and broken relative imports within
    the harness scripts dir."""
    path = _HARNESS / script
    if not path.exists():
        pytest.skip(f"{script} not present on this branch")
    result = subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(_HARNESS),
    )
    assert result.returncode == 0, f"{script} --help failed: {result.stderr}"
    assert "usage" in (result.stdout + result.stderr).lower()


HARNESS_SHARED_MODULES = [
    "_utils",
    "_task_io",
    "_feishu",
    "_heartbeat_helpers",
    "_common",
]


@pytest.mark.parametrize("module_name", HARNESS_SHARED_MODULES)
def test_harness_shared_module_imports(module_name: str) -> None:
    """Fresh-subprocess import — same rationale as
    test_admin_module_imports_cleanly. Sibling tests in this dir
    pre-populate sys.modules for these shared helpers, so an
    in-process import would no-op.
    """
    result = _import_in_subprocess(module_name, _HARNESS)
    assert result.returncode == 0, (
        f"import {module_name} failed:\n"
        f"STDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )


def _import_without_fcntl(module_name: str):
    import importlib
    import sys

    original_fcntl = sys.modules.pop("fcntl", None)
    original_module = sys.modules.pop(module_name, None)
    try:
        sys.modules["fcntl"] = None
        return importlib.import_module(module_name)
    finally:
        sys.modules.pop(module_name, None)
        sys.modules.pop("fcntl", None)
        if original_module is not None:
            sys.modules[module_name] = original_module
        if original_fcntl is not None:
            sys.modules["fcntl"] = original_fcntl


@pytest.mark.skipif(os.name != "nt", reason="Windows-only fcntl import regression")
def test_harness_task_io_imports_without_fcntl() -> None:
    module = _import_without_fcntl("_task_io")

    assert hasattr(module, "write_todo")


@pytest.mark.skipif(os.name != "nt", reason="Windows-only fcntl import regression")
def test_queue_io_imports_without_fcntl() -> None:
    module = _import_without_fcntl("queue_io")

    assert hasattr(module, "append_event")


def test_harness_task_io_renders_todo(tmp_path: Path) -> None:
    """Pure `write_todo` should produce TODO.md content with the
    schema documented in CANONICAL-FLOW.md §9."""
    from _task_io import write_todo

    target = tmp_path / "TODO.md"
    write_todo(
        target,
        task_id="T1",
        project="demo",
        owner="builder-1",
        status="pending",
        title="demo task",
        objective="do things",
        source="planner",
        reply_to="planner",
    )
    body = target.read_text(encoding="utf-8")
    for marker in ("task_id: T1", "project: demo", "owner: builder-1", "status: pending", "# Objective", "# Dispatch"):
        assert marker in body, marker


def test_harness_task_io_appends_consumed_ack_idempotent(tmp_path: Path) -> None:
    from _task_io import append_consumed_ack, find_consumed_ack

    delivery = tmp_path / "DELIVERY.md"
    delivery.write_text("task_id: T2\nstatus: completed\n", encoding="utf-8")
    first = append_consumed_ack(delivery, task_id="T2", source="builder-1")
    second = append_consumed_ack(delivery, task_id="T2", source="builder-1")
    assert first == second, "append_consumed_ack must be idempotent for the same (task, source)"
    assert find_consumed_ack(delivery, task_id="T2", source="builder-1") == first


# ── direct-entry core scripts (F11 regression) ──────────────────────

def test_preflight_runs_from_bare_checkout() -> None:
    """`python3 core/preflight.py …` must succeed on a checkout that has
    NOT been `pip install -e .`-installed. Preflight is the very first
    script a new operator runs (P0.0), so its import bootstrap cannot
    depend on the editable-install `.pth` file injecting the repo root
    into sys.path.

    We run under `python -S` to skip site.py (and therefore the
    `__editable__.clawseat-*.pth` that would silently make
    `from core.resolve import …` resolve against an already-installed
    copy of the repo). Without preflight.py's internal sys.path
    bootstrap this raises `ModuleNotFoundError: No module named 'core'`
    — exactly the stranger-reported F11 failure.
    """
    preflight = _REPO / "core" / "preflight.py"
    result = subprocess.run(
        [sys.executable, "-S", str(preflight), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd="/",  # arbitrary cwd outside the repo
    )
    assert "ModuleNotFoundError: No module named 'core'" not in result.stderr, (
        f"preflight.py bare-script import regressed:\nSTDERR:\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"preflight.py --help exit={result.returncode}:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "usage: preflight.py" in result.stdout, result.stdout


# ── migration/ layer smoke ──────────────────────────────────────────

MIGRATION_SCRIPTS = [
    "dispatch_task_dynamic.py",
    "notify_seat_dynamic.py",
    "complete_handoff_dynamic.py",
    "render_console_dynamic.py",
]


@pytest.mark.parametrize("script", MIGRATION_SCRIPTS)
def test_migration_script_help_runs(script: str) -> None:
    path = _MIGRATION / script
    if not path.exists():
        pytest.skip(f"{script} not present on this branch")
    result = subprocess.run(
        [sys.executable, str(path), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(_MIGRATION),
    )
    assert result.returncode == 0, f"{script} --help failed: {result.stderr}"
