from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_REPO / "tests") not in sys.path:
    sys.path.insert(0, str(_REPO / "tests"))

import projects_registry  # noqa: E402
from agent_admin_commands import CommandHandlers, CommandHooks  # noqa: E402
from test_install_isolation import _fake_install_root  # noqa: E402


def _env(tmp_path: Path) -> dict[str, str]:
    return {
        **os.environ,
        "CLAWSEAT_REGISTRY_HOME": str(tmp_path / ".clawseat"),
        "PYTHONPATH": f"{_SCRIPTS}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
    }


def test_v1_registry_loads_as_schema_v2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REGISTRY_HOME", str(tmp_path / ".clawseat"))
    root = tmp_path / ".clawseat"
    root.mkdir()
    (root / "projects.json").write_text(
        json.dumps(
            {
                "version": 1,
                "projects": [
                    {
                        "name": "install",
                        "primary_seat": "memory",
                        "tmux_name": "install-memory",
                        "registered_at": "2026-04-26T12:34:56Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    data = projects_registry.load_registry()
    assert data["version"] == 2
    entry = data["projects"][0]
    assert entry["name"] == "install"
    assert entry["primary_seat_tool"] == ""
    assert entry["template_name"] == ""
    assert entry["last_access"] == "2026-04-26T12:34:56Z"
    assert entry["status"] == "active"
    assert entry["metadata"] == {}


def test_register_project_writes_schema_v2_and_backup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REGISTRY_HOME", str(tmp_path / ".clawseat"))

    entry = projects_registry.register_project(
        "install",
        "memory",
        primary_seat_tool="codex",
        tmux_name="install-memory",
        template_name="clawseat-creative",
        repo_path="/repo",
        metadata={"owner": "ops"},
    )

    assert entry.primary_seat_tool == "codex"
    data = json.loads(projects_registry.registry_path().read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert data["projects"][0]["template_name"] == "clawseat-creative"
    assert data["projects"][0]["repo_path"] == "/repo"
    assert projects_registry.backup_path().is_file()
    assert oct(projects_registry.registry_path().stat().st_mode & 0o777) == "0o600"


def test_corrupt_registry_recovers_from_backup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REGISTRY_HOME", str(tmp_path / ".clawseat"))
    projects_registry.register_project("install", "memory", tmux_name="install-memory")
    projects_registry.registry_path().write_text("{broken", encoding="utf-8")

    data = projects_registry.load_registry()

    assert data["projects"][0]["name"] == "install"
    assert json.loads(projects_registry.registry_path().read_text(encoding="utf-8"))["version"] == 2


def test_cli_list_show_update_unregister(tmp_path: Path) -> None:
    env = _env(tmp_path)
    registry = _SCRIPTS / "projects_registry.py"
    subprocess.run(
        [
            sys.executable,
            str(registry),
            "register",
            "demo",
            "--primary-seat",
            "memory",
            "--primary-seat-tool",
            "codex",
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    listed = subprocess.run(
        [sys.executable, str(registry), "list"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "demo\tactive\tmemory" in listed.stdout

    updated = subprocess.run(
        [sys.executable, str(registry), "update", "demo", "--status", "archived"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(updated.stdout)["status"] == "archived"

    shown = subprocess.run(
        [sys.executable, str(registry), "show", "demo"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(shown.stdout)["primary_seat_tool"] == "codex"

    removed = subprocess.run(
        [sys.executable, str(registry), "unregister", "demo"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "unregistered demo" in removed.stdout


def test_clawseat_cli_projects_wrapper(tmp_path: Path) -> None:
    env = _env(tmp_path)
    registry = _SCRIPTS / "projects_registry.py"
    subprocess.run(
        [sys.executable, str(registry), "register", "demo", "--primary-seat", "memory"],
        env=env,
        check=True,
    )

    result = subprocess.run(
        ["bash", str(_SCRIPTS / "clawseat-cli.sh"), "projects", "show", "demo"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["name"] == "demo"


def test_validate_registry_vs_project_toml_warns_on_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REGISTRY_HOME", str(tmp_path / ".clawseat"))
    agents = tmp_path / ".agents"
    project_dir = agents / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "project.toml").write_text(
        "\n".join(
            [
                'name = "demo"',
                'template_name = "clawseat-creative"',
                'engineers = ["memory", "planner"]',
                "",
                "[seat_overrides.memory]",
                'tool = "codex"',
            ]
        ),
        encoding="utf-8",
    )
    projects_registry.register_project(
        "demo",
        "ancestor",
        primary_seat_tool="claude",
        template_name="clawseat-engineering",
    )

    warnings = projects_registry.validate_registry_vs_project_toml("demo", agents_home=agents)

    assert "primary_seat mismatch" in "\n".join(warnings)
    assert "primary_seat_tool mismatch" in "\n".join(warnings)
    assert "template_name mismatch" in "\n".join(warnings)


def test_cli_validate_prints_one_line_status_and_quiet_suppresses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REGISTRY_HOME", str(tmp_path / ".clawseat"))
    agents = tmp_path / ".agents"
    project_dir = agents / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "project.toml").write_text(
        "\n".join(
            [
                'name = "demo"',
                'template_name = "clawseat-creative"',
                'engineers = ["memory", "planner"]',
                "",
                "[seat_overrides.memory]",
                'tool = "codex"',
            ]
        ),
        encoding="utf-8",
    )
    projects_registry.register_project(
        "demo",
        "ancestor",
        primary_seat_tool="claude",
        template_name="clawseat-engineering",
    )

    env = _env(tmp_path)
    env["HOME"] = str(tmp_path)
    registry = _SCRIPTS / "projects_registry.py"
    result = subprocess.run(
        [sys.executable, str(registry), "validate", "demo"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout.strip() == (
        "projects_registry validate demo: FAIL — "
        "primary_seat mismatch: registry=ancestor project.toml=memory; "
        "primary_seat_tool mismatch: registry=claude project.toml=codex; "
        "template_name mismatch: registry=clawseat-engineering project.toml=clawseat-creative"
    )

    quiet = subprocess.run(
        [sys.executable, str(registry), "validate", "demo", "--quiet"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert quiet.returncode == 1
    assert quiet.stdout == ""


def test_agent_admin_start_engineer_touches_last_access(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAWSEAT_REGISTRY_HOME", str(tmp_path / ".clawseat"))
    caller_profile = tmp_path / "caller.toml"
    caller_profile.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "planner"',
                'display_name = "planner"',
                'role = "planner"',
                "dispatch_authority = true",
                "escalation_authority = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(caller_profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")
    projects_registry.register_project("demo", "memory", tmux_name="demo-memory")
    before = projects_registry.get_project("demo").last_access  # type: ignore[union-attr]
    time.sleep(0.001)

    class _Service:
        def start_engineer(self, session, reset=False):
            return None

    hooks = CommandHooks(
        error_cls=RuntimeError,
        load_project_or_current=lambda _project=None: None,
        resolve_engineer_session=lambda *_args, **_kwargs: SimpleNamespace(
            engineer_id="memory",
            project="demo",
            session="demo-memory",
        ),
        provision_session_heartbeat=lambda _session: (False, ""),
        load_project_sessions=lambda _project: {},
        tmux_has_session=lambda _session: True,
        load_projects=lambda: {},
        get_current_project_name=lambda _projects: None,
        session_service=_Service(),
        open_monitor_window=lambda *_args, **_kwargs: None,
        open_dashboard_window=lambda *_args, **_kwargs: None,
        open_project_tabs_window=lambda *_args, **_kwargs: None,
        open_engineer_window=lambda *_args, **_kwargs: None,
        load_engineers=lambda: {},
    )

    rc = CommandHandlers(hooks).session_start_engineer(
        SimpleNamespace(engineer="memory", project="demo", reset=False)
    )

    after = projects_registry.get_project("demo").last_access  # type: ignore[union-attr]
    assert rc == 0
    assert after != before


def test_install_uninstall_unregisters_project(tmp_path: Path) -> None:
    root, home, _launcher_log, _tmux_log, py_stubs = _fake_install_root(tmp_path)
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        "PYTHON_BIN": sys.executable,
    }
    registry = root / "core" / "scripts" / "projects_registry.py"
    subprocess.run(
        [sys.executable, str(registry), "register", "demo", "--primary-seat", "memory"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"), "--uninstall", "demo"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert "unregistered demo" in result.stdout
    assert subprocess.run(
        [sys.executable, str(registry), "show", "demo"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 1
