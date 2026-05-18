from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"
_LAUNCHER = _REPO / "core" / "launchers" / "agent-launcher.sh"
_TEMPLATE = _REPO / "core" / "templates" / "gstack-harness" / "template.toml"

sys.path.insert(0, str(_REPO / "core" / "scripts"))
import agent_admin  # noqa: E402
import agent_admin_window  # noqa: E402


def _run_install_dry(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_INSTALL), "--dry-run", "--project", "qa-gaps", *extra],
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "CLAWSEAT_REAL_HOME": str(tmp_path / "home"),
            "PYTHON_BIN": sys.executable,
            "CLAWSEAT_QA_PATROL_CRON_OPT_IN": "n",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_fake_install(
    tmp_path: Path,
    *,
    project_toml_text: str,
    migrate: str = "y",
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    from tests.test_install_isolation import _fake_install_root

    root, home, _launcher_log, _tmux_log, py_stubs = _fake_install_root(tmp_path)
    shutil.copytree(_REPO / "templates", root / "templates", dirs_exist_ok=True)
    project_dir = home / ".agents" / "projects" / "qa-gaps"
    project_dir.mkdir(parents=True)
    project_toml = project_dir / "project.toml"
    project_toml.write_text(project_toml_text, encoding="utf-8")
    agent_admin_log = tmp_path / "agent-admin.jsonl"

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--project",
            "qa-gaps",
            "--provider",
            "minimax",
        ],
        input="\n",
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(tmp_path / "launcher.jsonl"),
            "TMUX_LOG_FILE": str(tmp_path / "tmux.log"),
            "AGENT_ADMIN_LOG": str(agent_admin_log),
            "CLAWSEAT_QA_PROFILE_MIGRATE": migrate,
            "CLAWSEAT_QA_PATROL_CRON_OPT_IN": "n",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result, project_toml, agent_admin_log


def test_migrate_project_profile_adds_patrol(tmp_path: Path) -> None:
    result, project_toml, agent_admin_log = _run_fake_install(
        tmp_path,
        project_toml_text="\n".join(
            [
                'name = "qa-gaps"',
                'template_name = "clawseat-engineering"',
                'engineers = ["memory", "planner", "builder", "reviewer"]',
                'monitor_engineers = ["memory", "planner", "builder", "reviewer"]',
                "monitor_max_panes = 4",
                "",
                "[seat_overrides.builder]",
                'provider = "openai"',
                "",
            ]
        ),
    )

    assert result.returncode == 0, result.stderr
    migrated = tomllib.loads(project_toml.read_text(encoding="utf-8"))
    assert migrated["engineers"] == ["memory", "planner", "builder", "reviewer", "patrol"]
    assert migrated["monitor_engineers"] == ["memory", "planner", "builder", "reviewer", "patrol"]
    assert migrated["monitor_max_panes"] == 5
    assert migrated["seat_overrides"]["builder"]["provider"] == "openai"
    assert migrated["seat_overrides"]["patrol"]["auth_mode"] == "api"
    assert migrated["seat_overrides"]["patrol"]["provider"] == "minimax"
    assert migrated["seat_overrides"]["patrol"]["model"] == "MiniMax-M2.7-highspeed"
    assert migrated["seat_overrides"]["patrol"]["base_url"] == "https://api.minimaxi.com/anthropic"
    assert list(project_toml.parent.glob("project.toml.bak.*"))
    calls = [
        json.loads(line)["argv"]
        for line in agent_admin_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert ["engineer", "create", "patrol", "qa-gaps", "--no-monitor"] in calls


def test_migrate_project_profile_skips_if_patrol_present(tmp_path: Path) -> None:
    original = "\n".join(
        [
            'name = "qa-gaps"',
            'template_name = "clawseat-engineering"',
            'engineers = ["memory", "planner", "builder", "reviewer", "patrol"]',
            'monitor_engineers = ["memory", "planner", "builder", "reviewer", "patrol"]',
            "monitor_max_panes = 5",
            "",
            "[seat_overrides.memory]",
            'tool = "claude"',
            'auth_mode = "oauth"',
            'provider = "anthropic"',
            "",
            "[seat_overrides.planner]",
            'tool = "claude"',
            'auth_mode = "api"',
            'provider = "deepseek"',
            'model = "deepseek-v4-pro[1M]"',
            "",
            "[seat_overrides.builder]",
            'tool = "codex"',
            'auth_mode = "oauth"',
            'provider = "openai"',
            "",
            "[seat_overrides.patrol]",
            'tool = "claude"',
            'auth_mode = "api"',
            'provider = "minimax"',
            'model = "MiniMax-M2.7-highspeed"',
            'base_url = "https://api.minimaxi.com/anthropic"',
            "",
            "[seat_overrides.reviewer]",
            'tool = "claude"',
            'auth_mode = "oauth"',
            'provider = "anthropic"',
            "",
        ]
    )
    result, project_toml, _agent_admin_log = _run_fake_install(tmp_path, project_toml_text=original)

    assert result.returncode == 0, result.stderr
    assert project_toml.read_text(encoding="utf-8") == original
    assert not list(project_toml.parent.glob("project.toml.bak.*"))


def test_install_dry_run_registers_memory_tmux_with_tool_suffix(tmp_path: Path) -> None:
    result = _run_install_dry(tmp_path, "--memory-tool", "codex")
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "--primary-seat-tool codex" in combined
    assert "--tmux-name qa-gaps-memory-codex" in combined


def test_gstack_harness_template_has_patrol() -> None:
    template = tomllib.loads(_TEMPLATE.read_text(encoding="utf-8"))
    patrol_specs = [eng for eng in template["engineers"] if eng.get("id") == "patrol"]

    assert len(patrol_specs) == 1
    assert patrol_specs[0]["role"] == "patrol"
    assert patrol_specs[0]["patrol_authority"] is True
    assert patrol_specs[0]["auth_mode"] == "api"
    assert patrol_specs[0]["provider"] == "minimax"
    assert patrol_specs[0]["model"] == "MiniMax-M2.7-highspeed"
    assert patrol_specs[0]["base_url"] == "https://api.minimaxi.com/anthropic"


def test_agent_launcher_session_has_tool_suffix(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(_LAUNCHER),
            "--tool",
            "claude",
            "--auth",
            "oauth_token",
            "--session",
            "qa-gaps-memory",
            "--dir",
            str(tmp_path),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "session:  qa-gaps-memory-claude" in result.stdout


def test_open_grid_rebuild_flag_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = agent_admin.build_parser()
    args = parser.parse_args(["window", "open-grid", "qa-gaps", "--recover", "--rebuild"])

    assert args.rebuild is True
    assert args.recover is True

    project = type(
        "Project",
        (),
        {
            "name": "qa-gaps",
            "engineers": ["memory", "planner", "builder", "patrol"],
            "template_name": "clawseat-creative",
        },
    )()
    closed: list[str] = []
    focused: list[str] = []
    payloads: list[dict] = []
    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda _title: True)
    monkeypatch.setattr(agent_admin_window, "close_iterm_window", lambda title: closed.append(title) or True)
    monkeypatch.setattr(agent_admin_window, "focus_iterm_window", lambda title: focused.append(title))
    monkeypatch.setattr(agent_admin_window, "_tmux_session_names", lambda: [])
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    result = agent_admin_window.open_grid_window(project, recover=True, rebuild=True)

    assert closed == ["clawseat-qa-gaps-workers"]
    assert focused == []
    assert payloads and payloads[0]["title"] == "clawseat-qa-gaps-workers"
    assert result["recovered"] is False
    assert result["rebuilt"] is True


def test_workers_recipe_4_is_balanced() -> None:
    assert agent_admin_window._workers_recipe(4) == [[0, True], [0, False], [1, False]]


def test_workers_recipe_4_pane_labels() -> None:
    project = SimpleNamespace(
        name="qa-gaps",
        engineers=["memory", "planner", "builder", "designer", "patrol"],
        template_name="clawseat-creative",
    )

    payload = agent_admin_window.build_workers_payload(project)

    assert payload["recipe"] == [[0, True], [0, False], [1, False]]
    assert [pane["label"] for pane in payload["panes"]] == ["planner", "builder", "designer", "patrol"]


def test_agent_admin_engineer_create_uses_patrol_minimax_defaults(tmp_path: Path, monkeypatch) -> None:
    from agent_admin_crud import CrudHandlers

    caller_profile = tmp_path / "caller.toml"
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
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(caller_profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")

    created_sessions: list[dict[str, object]] = []
    write_project_calls: list[object] = []
    project = SimpleNamespace(
        name="qa-gaps",
        engineers=["memory", "planner", "builder", "designer"],
        monitor_engineers=["planner", "builder", "designer"],
        template_name="clawseat-creative",
    )
    session = SimpleNamespace(
        engineer_id="patrol",
        project="qa-gaps",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        monitor=False,
        runtime_dir="/tmp/runtime",
        secret_file="",
    )
    hooks = SimpleNamespace(
        error_cls=RuntimeError,
        load_projects=lambda: {"qa-gaps": project},
        load_template=lambda _name: {
            "engineers": [
                {
                    "id": "patrol",
                    "tool": "claude",
                    "auth_mode": "api",
                    "provider": "minimax",
                }
            ]
        },
        normalize_name=lambda name: name,
        session_path=lambda _project, _engineer: Path("/tmp/nonexistent-session.toml"),
        engineer_path=lambda _engineer: Path("/tmp/nonexistent-engineer.toml"),
        load_engineer=lambda _engineer: None,
        create_engineer_profile=lambda **kwargs: SimpleNamespace(**kwargs),
        write_engineer=lambda _profile: None,
        create_session_record=lambda **kwargs: created_sessions.append(kwargs) or session,
        write_session=lambda _session: None,
        apply_template=lambda _session, _project: None,
        ensure_dir=lambda _path: None,
        write_env_file=lambda *_args: None,
        write_project=lambda _project: write_project_calls.append(_project),
    )

    rc = CrudHandlers(hooks).engineer_create(
        SimpleNamespace(engineer="patrol", project="qa-gaps", tool=None, mode=None, provider=None, no_monitor=True)
    )

    assert rc == 0
    assert created_sessions[0]["engineer_id"] == "patrol"
    assert created_sessions[0]["tool"] == "claude"
    assert created_sessions[0]["auth_mode"] == "api"
    assert created_sessions[0]["provider"] == "minimax"
    assert created_sessions[0]["monitor"] is False
    assert project.engineers == ["memory", "planner", "builder", "designer"]
    assert project.monitor_engineers == ["planner", "builder", "designer"]
    assert write_project_calls == []
