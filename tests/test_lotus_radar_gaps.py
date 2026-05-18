from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


REPO = Path(__file__).resolve().parents[1]
# CLAWSEAT_ROOT may override the template renderer's repo root (e.g. when running from a worktree)
CLAWSEAT_ROOT = Path(os.environ.get("CLAWSEAT_ROOT", str(REPO)))
AGENT_ADMIN = REPO / "core" / "scripts" / "agent_admin.py"
TESTS_DIR = REPO / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))


def _run_agent_admin(
    home: Path,
    *args: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CLAWSEAT_REAL_HOME": str(home),
        "PYTHONPATH": f"{REPO / 'core' / 'skills' / 'gstack-harness' / 'scripts'}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(AGENT_ADMIN), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_project_create_generates_complete_project_toml(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "lotus-radar"
    repo.mkdir()
    result = _run_agent_admin(home, "project", "create", "lotus-radar", str(repo))

    assert result.returncode == 0, result.stderr
    data = _load_toml(home / ".agents" / "projects" / "lotus-radar" / "project.toml")
    assert data["template_name"] == "clawseat-engineering"
    assert data["window_mode"] == "split-2"
    assert data["monitor_max_panes"] == 5
    assert data["engineers"] == ["memory", "planner", "builder", "reviewer", "patrol"]
    assert data["monitor_engineers"] == data["engineers"]
    assert set(data["seat_overrides"]) == set(data["engineers"])


def test_project_create_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    first = _run_agent_admin(home, "project", "create", "foo", str(repo))
    assert first.returncode == 0, first.stderr
    project_toml = home / ".agents" / "projects" / "foo" / "project.toml"
    original = project_toml.read_text(encoding="utf-8")
    project_toml.write_text(original.replace('window_mode = "split-2"', 'window_mode = "custom-keep"'), encoding="utf-8")

    second = _run_agent_admin(home, "project", "create", "foo", str(repo))

    assert second.returncode == 0, second.stderr
    assert 'window_mode = "custom-keep"' in project_toml.read_text(encoding="utf-8")


def test_role_skill_uses_clawseat_root(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "not-clawseat"
    repo.mkdir()
    assert _run_agent_admin(home, "project", "create", "foo", str(repo)).returncode == 0
    caller_profile = home / ".agents" / "caller.toml"
    caller_profile.parent.mkdir(parents=True, exist_ok=True)
    caller_profile.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "planner"',
                'display_name = "planner"',
                'role = "planner"',
                "dispatch_authority = false",
                "escalation_authority = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    result = _run_agent_admin(
        home,
        "engineer",
        "create",
        "patrol",
        "foo",
        "--no-monitor",
        extra_env={
            "CLAWSEAT_ENGINEER_PROFILE": str(caller_profile),
            "CLAWSEAT_ENGINEER_ID": "planner",
            "CLAWSEAT_SEAT": "planner",
        },
    )

    assert result.returncode == 0, result.stderr
    claude_md = home / ".agents" / "workspaces" / "foo" / "patrol" / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    assert "Primary repo root: `" + str(repo) + "`" in text
    assert "## Role SKILL (canonical)" in text
    assert "# Patrol" in text


def test_removed_qa_engineer_alias_is_not_accepted(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "not-clawseat"
    repo.mkdir()
    assert _run_agent_admin(home, "project", "create", "foo", str(repo)).returncode == 0

    result = _run_agent_admin(home, "engineer", "create", "qa", "foo", "--no-monitor")

    assert result.returncode != 0


def test_workspace_memory_template_has_absolute_send_verify_path() -> None:
    from test_workspace_memory_template import _handlers, _project, _session

    rendered = _handlers().render_template_text("claude", _session("claude"), _project())
    text = rendered["CLAUDE.md"]
    assert f"{CLAWSEAT_ROOT}/core/shell-scripts/send-and-verify.sh --project cartooner" in text
    assert "`core/shell-scripts/send-and-verify.sh" not in text


def test_clawseat_root_variable_in_template_renderer() -> None:
    from test_workspace_memory_template import _handlers, _project, _session

    rendered = _handlers().render_template_text("gemini", _session("gemini"), _project())
    text = rendered["GEMINI.md"]
    assert "{{clawseat_root}}" not in text
    assert f"{CLAWSEAT_ROOT}/docs/rfc/RFC-002-architecture-v2.1.md" in text


def test_planner_skill_has_cross_tool_delivery_protocol() -> None:
    text = (REPO / "core" / "skills" / "planner" / "SKILL.md").read_text(encoding="utf-8")
    assert "跨 Tool 交付协议" in text
    assert "complete_handoff.py" in text
    assert "send-and-verify.sh" in text
    assert "Claude Code convenience only" in text


def test_memory_oracle_skill_has_cross_tool_delivery_protocol() -> None:
    text = (REPO / "core" / "skills" / "memory-oracle" / "SKILL.md").read_text(encoding="utf-8")
    assert "跨 Tool 交付协议" in text
    assert "memory_deliver.py" in text
    assert "complete_handoff.py" in text
    assert "primary delivery mechanism" in text


def test_project_create_generates_profile(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "foo"
    repo.mkdir()
    result = _run_agent_admin(home, "project", "create", "foo", str(repo))

    assert result.returncode == 0, result.stderr
    profile = home / ".agents" / "profiles" / "foo-profile-dynamic.toml"
    data = _load_toml(profile)
    assert data["project_name"] == "foo"
    assert data["send_script"] == str(REPO / "core" / "shell-scripts" / "send-and-verify.sh")
    assert data["agent_admin"] == str(REPO / "core" / "scripts" / "agent_admin.py")
    assert data["handoff_dir"] == str(home / ".agents" / "tasks" / "foo" / "patrol" / "handoffs")
    assert data["dynamic_roster"]["session_root"] == str(home / ".agents" / "sessions")


def test_project_create_profile_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "foo"
    repo.mkdir()
    profile = home / ".agents" / "profiles" / "foo-profile-dynamic.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text("sentinel = true\n", encoding="utf-8")

    result = _run_agent_admin(home, "project", "create", "foo", str(repo))

    assert result.returncode == 0, result.stderr
    assert profile.read_text(encoding="utf-8") == "sentinel = true\n"
