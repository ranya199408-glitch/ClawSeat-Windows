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
    template_name: str = "clawseat-creative",
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


def test_open_grid_parser_accepts_memory_flags() -> None:
    parser = agent_admin.build_parser()
    args = parser.parse_args(
        ["window", "open-grid", "spawn49", "--rebuild", "--open-memory", "--refresh-memories"]
    )

    assert args.open_memory is True
    assert args.refresh_memories is True


def test_open_grid_rebuild_defaults_workers_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(["memory", "planner", "builder"])

    payloads: list[dict] = []
    memory_calls: list[str] = []
    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )
    monkeypatch.setattr(
        agent_admin_window,
        "ensure_memories_pane",
        lambda _project: memory_calls.append(_project.name) or {"status": "ok", "window_id": "clawseat-memories"},
    )

    result = agent_admin_window.open_grid_window(project, rebuild=True)

    assert [payload["title"] for payload in payloads] == ["clawseat-spawn49-workers"]
    assert memory_calls == []
    assert result["memories"]["status"] == "skipped"
    assert "DEPRECATED: --rebuild no longer refreshes memories by default." in capsys.readouterr().err


def test_open_grid_rebuild_with_refresh_memories_touches_memories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(["memory", "planner", "builder", "designer"])

    payloads: list[dict] = []
    monkeypatch.setattr(agent_admin_window, "iterm_window_exists", lambda title: False)
    monkeypatch.setattr(agent_admin_window, "_tmux_session_names", lambda: ["spawn49-memory"])
    monkeypatch.setattr(
        agent_admin_window,
        "run_iterm_panes_driver",
        lambda payload: payloads.append(payload) or {"status": "ok", "window_id": payload["title"]},
    )

    result = agent_admin_window.open_grid_window(project, rebuild=True, refresh_memories=True)

    assert [payload["title"] for payload in payloads] == [
        "clawseat-spawn49-workers",
        "clawseat-memories",
    ]
    assert result["memories"]["status"] == "ok"


def test_window_open_grid_summary_includes_memories_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(["memory", "planner", "builder"], template_name="clawseat-creative")
    handlers = _handlers({"spawn49": project})

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            agent_admin_window,
            "open_grid_window",
            lambda *args, **kwargs: {"status": "ok", "window_id": "grid", "memories": {"status": "ok"}},
        )

        rc = handlers.window_open_grid(
            SimpleNamespace(
                project="spawn49",
                recover=False,
                rebuild=False,
                open_memory=False,
                refresh_memories=False,
                quiet=False,
            )
        )

    assert rc == 0
    assert (
        capsys.readouterr().out.strip()
        == "window open-grid: rebuilt project=spawn49 seats=2 memories=touched"
    )
