from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))

import agent_admin  # noqa: E402
import agent_admin_window  # noqa: E402
from agent_admin_commands import CommandHandlers, CommandHooks  # noqa: E402


def _project(
    engineers: list[str],
    *,
    name: str = "spawn49",
    template_name: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        engineers=engineers,
        monitor_session=f"project-{name}-monitor",
        repo_root=str(_REPO),
        template_name=template_name,
    )


def _handlers(projects: dict[str, SimpleNamespace]) -> CommandHandlers:
    return CommandHandlers(
        CommandHooks(
            error_cls=RuntimeError,
            load_project_or_current=lambda _name: next(iter(projects.values())) if projects else None,
            resolve_engineer_session=lambda *a, **k: None,
            provision_session_heartbeat=lambda *a, **k: (True, ""),
            load_project_sessions=lambda _project: {},
            tmux_has_session=lambda _name: False,
            load_projects=lambda: projects,
            get_current_project_name=lambda _projects: None,
            session_service=SimpleNamespace(),
            open_monitor_window=lambda *a, **k: None,
            open_dashboard_window=lambda *a, **k: None,
            open_project_tabs_window=lambda *a, **k: None,
            open_engineer_window=lambda *a, **k: None,
            load_engineers=lambda: {},
        )
    )


def test_parser_registers_open_grid_flags() -> None:
    parser = agent_admin.build_parser()
    args = parser.parse_args(["window", "open-grid", "spawn49", "--recover", "--open-memory", "--quiet"])

    assert args.command == "window"
    assert args.window_command == "open-grid"
    assert args.project == "spawn49"
    assert args.recover is True
    assert args.open_memory is True
    assert args.quiet is True


def test_build_grid_payload_uses_project_roster_and_wait_for_seat_commands() -> None:
    project = _project(
        [
            "ancestor",
            "planner",
            "koder",
            "builder",
            "reviewer",
            "patrol",
            "designer",
        ]
    )

    payload = agent_admin_window.build_grid_payload(project)

    assert payload["title"] == "clawseat-spawn49"
    commands = {pane["label"]: pane["command"] for pane in payload["panes"]}
    assert commands["ancestor"] == "tmux attach -t '=spawn49-ancestor'"
    assert "koder" not in commands
    for seat in ("planner", "builder", "reviewer", "patrol", "designer"):
        assert commands[seat] == f"bash {_REPO / 'scripts' / 'wait-for-seat.sh'} spawn49 {seat}"


def test_build_workers_payload_creative_3workers() -> None:
    project = _project(
        ["memory", "planner", "builder", "designer"],
        template_name="clawseat-creative",
    )

    payload = agent_admin_window.build_workers_payload(project)

    assert payload["title"] == "clawseat-spawn49-workers"
    assert [pane["label"] for pane in payload["panes"]] == ["planner", "builder", "designer"]
    assert payload["recipe"] == [[0, True], [1, False]]
    commands = {pane["label"]: pane["command"] for pane in payload["panes"]}
    for seat in ("planner", "builder", "designer"):
        assert commands[seat] == f"bash {_REPO / 'scripts' / 'wait-for-seat.sh'} spawn49 {seat}"


def test_build_memories_payload_returns_tabs_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_admin_window.projects_registry, "enumerate_projects", lambda: [])
    monkeypatch.setattr(
        agent_admin_window,
        "_tmux_session_names",
        lambda: ["install-memory", "foo-memory", "machine-memory-claude"],
    )

    payload = agent_admin_window.build_memories_payload(_project(["memory"]))

    assert payload == {
        "mode": "tabs",
        "title": "clawseat-memories",
        "tabs": [
            {"name": "foo", "command": "tmux attach -t '=foo-memory'"},
            {"name": "install", "command": "tmux attach -t '=install-memory'"},
        ],
        "ensure": True,
    }


def test_build_memories_payload_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agent_admin_window.projects_registry, "enumerate_projects", lambda: [])
    monkeypatch.setattr(
        agent_admin_window,
        "_tmux_session_names",
        lambda: ["machine-memory-claude", "install-planner-claude"],
    )

    assert agent_admin_window.build_memories_payload(_project(["memory"])) is None


def test_open_grid_recover_skips_driver_when_window_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(["ancestor", "planner"])
    focus_calls: list[str] = []
    driver_calls: list[dict] = []

    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: title == "clawseat-spawn49")
    monkeypatch.setattr(agent_admin_window, "focus_iterm_window", lambda title: focus_calls.append(title))
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: driver_calls.append(payload) or {"status": "ok", "window_id": "grid"},
    )

    result = agent_admin_window.open_grid_window(project, recover=True)

    assert result["recovered"] is True
    assert focus_calls == ["clawseat-spawn49"]
    assert driver_calls == []


def test_open_grid_window_memory_template_calls_workers_and_memories(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(
        ["memory", "planner", "builder", "designer"],
        template_name="clawseat-creative",
    )
    payloads: list[dict] = []

    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(agent_admin_window, "_tmux_session_names", lambda: ["spawn49-memory"])
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    result = agent_admin_window.open_grid_window(project, open_memory=True)

    assert [payload["title"] for payload in payloads] == [
        "clawseat-spawn49-workers",
        "clawseat-memories",
    ]
    assert [pane["label"] for pane in payloads[0]["panes"]] == ["planner", "builder", "designer"]
    assert payloads[1]["mode"] == "tabs"
    assert result["memories"]["status"] == "ok"
    assert result["memory"]["status"] == "skipped"


def test_open_grid_window_default_keeps_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(["ancestor", "planner", "builder"], template_name="legacy-ancestor")
    payloads: list[dict] = []

    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    result = agent_admin_window.open_grid_window(project)

    assert [payload["title"] for payload in payloads] == ["clawseat-spawn49"]
    assert [pane["label"] for pane in payloads[0]["panes"]] == ["ancestor", "planner", "builder"]
    assert "memories" not in result
    assert "memory" not in result


def test_open_grid_window_unknown_template_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(["ancestor", "planner"], template_name="custom-foo")
    payloads: list[dict] = []

    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    result = agent_admin_window.open_grid_window(project)

    assert result["recovered"] is False
    assert [payload["title"] for payload in payloads] == ["clawseat-spawn49"]
    assert "unknown template_name 'custom-foo'" in capsys.readouterr().err


def test_window_open_grid_prints_summary_by_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(["ancestor", "planner", "builder"])
    handlers = _handlers({"spawn49": project})

    monkeypatch.setattr(
        agent_admin_window,
        "open_grid_window",
        lambda *args, **kwargs: {"status": "ok", "window_id": "grid"},
    )

    rc = handlers.window_open_grid(
        SimpleNamespace(project="spawn49", recover=False, rebuild=False, open_memory=False, quiet=False)
    )

    assert rc == 0
    assert capsys.readouterr().out.strip() == "window open-grid: rebuilt project=spawn49 seats=3"


def test_window_open_grid_quiet_suppresses_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(["ancestor", "planner", "builder"])
    handlers = _handlers({"spawn49": project})

    monkeypatch.setattr(
        agent_admin_window,
        "open_grid_window",
        lambda *args, **kwargs: {"status": "ok", "window_id": "grid"},
    )

    rc = handlers.window_open_grid(
        SimpleNamespace(project="spawn49", recover=False, rebuild=False, open_memory=False, quiet=True)
    )

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_open_grid_open_memory_is_v1_compat_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _project(["ancestor", "planner", "builder"])
    payloads: list[dict] = []

    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    result = agent_admin_window.open_grid_window(project, open_memory=True)

    assert [payload["title"] for payload in payloads] == ["clawseat-spawn49"]
    assert payloads[0]["panes"][0]["command"] == "tmux attach -t '=spawn49-ancestor'"
    assert result["memory"] == {"status": "skipped", "reason": "global memory window retired"}


def test_open_grid_rejects_unregistered_project() -> None:
    handlers = _handlers({})

    with pytest.raises(RuntimeError, match="project not registered"):
        handlers.window_open_grid(
            SimpleNamespace(project="ghost", recover=False, open_memory=False)
        )


def test_open_grid_empty_roster_uses_memory_fallback_and_rejects_no_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project([])
    payloads: list[dict] = []

    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(agent_admin_window, "tmux_has_session", lambda session: False)
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    with pytest.raises(agent_admin_window.AgentAdminWindowError, match="no worker seats"):
        agent_admin_window.open_grid_window(project)

    assert payloads == []
