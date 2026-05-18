"""C6 regression: send-and-verify.sh refuses to run unscoped in multi-project mode.

P1 ask from the P0/P1 hardening list:

    project-scoped logs / closeout 强制带项目名 — 所有 closeout、提醒、
    Feishu envelope、tmux 唤醒都强制包含 project=...

Threat: without --project and without CLAWSEAT_PROJECT, the transport
script falls through to `agentctl session-name SESSION` which resolves
to *any* project's seat with a matching id. On multi-project installs
that means a reminder addressed to install's `planner` can land in
cartooner's planner pane (or vice-versa).

Guardrail: when `~/.agents/tasks/*/PROJECT_BINDING.toml` lists more
than one project, the script exits 3 (PROJECT_REQUIRED) unless the
caller passes --project, sets CLAWSEAT_PROJECT=..., or explicitly opts
out with CLAWSEAT_SEND_ALLOW_NO_PROJECT=1.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core" / "shell-scripts" / "send-and-verify.sh"
PROJECT_REQUIRED_RC = 3


def _fake_tasks_dir(tmp_path: Path, *project_names: str) -> Path:
    """Seed tmp_path/tasks/<name>/PROJECT_BINDING.toml for each name."""
    tasks = tmp_path / ".agents" / "tasks"
    for name in project_names:
        project_dir = tasks / name
        project_dir.mkdir(parents=True)
        (project_dir / "PROJECT_BINDING.toml").write_text(
            f'project = "{name}"\n'
            f'feishu_group_id = "oc_{name}_test"\n'
        )
    return tasks


def _env_with_real_home(real_home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["CLAWSEAT_REAL_HOME"] = str(real_home)
    env["HOME"] = str(real_home)
    # Scrub escape hatches unless the test sets them.
    env.pop("CLAWSEAT_PROJECT", None)
    env.pop("CLAWSEAT_SEND_ALLOW_NO_PROJECT", None)
    return env


def _run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )


# ── Guardrail trips when >1 binding exists ────────────────────────────


def test_multi_project_without_scope_hard_fails(tmp_path):
    _fake_tasks_dir(tmp_path, "install", "cartooner")
    env = _env_with_real_home(tmp_path)
    result = _run(["koder", "hello"], env)
    assert result.returncode == PROJECT_REQUIRED_RC, (
        f"expected PROJECT_REQUIRED (rc={PROJECT_REQUIRED_RC}), got rc={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "PROJECT_REQUIRED" in result.stderr
    assert "multi_project_mode_no_scope" in result.stderr
    assert "bindings_found: 2" in result.stderr


def test_multi_project_with_explicit_project_bypasses(tmp_path):
    """--project given: guardrail does not trip; downstream behavior
    proceeds (and will fail later for its own reasons like missing
    tmux session, which is NOT rc=3)."""
    _fake_tasks_dir(tmp_path, "install", "cartooner")
    env = _env_with_real_home(tmp_path)
    result = _run(["--project", "install", "nonexistent-session", "hello"], env)
    assert result.returncode != PROJECT_REQUIRED_RC, (
        f"explicit --project should bypass the guardrail, got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )


def test_multi_project_with_env_var_project_bypasses(tmp_path):
    _fake_tasks_dir(tmp_path, "install", "cartooner")
    env = _env_with_real_home(tmp_path)
    env["CLAWSEAT_PROJECT"] = "install"
    result = _run(["nonexistent-session", "hello"], env)
    assert result.returncode != PROJECT_REQUIRED_RC, (
        f"CLAWSEAT_PROJECT should bypass the guardrail, got rc={result.returncode}\n"
        f"stderr={result.stderr}"
    )


def test_explicit_opt_out_env_bypasses(tmp_path):
    _fake_tasks_dir(tmp_path, "install", "cartooner")
    env = _env_with_real_home(tmp_path)
    env["CLAWSEAT_SEND_ALLOW_NO_PROJECT"] = "1"
    result = _run(["nonexistent-session", "hello"], env)
    assert result.returncode != PROJECT_REQUIRED_RC


# ── Guardrail does NOT trip with 0 or 1 binding ───────────────────────


def test_single_project_no_scope_is_allowed(tmp_path):
    _fake_tasks_dir(tmp_path, "install")
    env = _env_with_real_home(tmp_path)
    result = _run(["koder", "hello"], env)
    assert result.returncode != PROJECT_REQUIRED_RC, (
        "single-project installs should keep the legacy unscoped behavior"
    )


def test_zero_projects_no_scope_is_allowed(tmp_path):
    # Fresh install before any binding lands.
    env = _env_with_real_home(tmp_path)
    result = _run(["koder", "hello"], env)
    assert result.returncode != PROJECT_REQUIRED_RC


def test_tasks_dir_missing_is_allowed(tmp_path):
    """A real_home without a tasks/ dir at all (brand-new machine) must
    not confuse the guardrail — the check should no-op."""
    empty_home = tmp_path / "empty"
    empty_home.mkdir()
    env = _env_with_real_home(empty_home)
    result = _run(["koder", "hello"], env)
    assert result.returncode != PROJECT_REQUIRED_RC
