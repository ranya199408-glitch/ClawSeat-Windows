from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture(autouse=True)
def _caller_escalation_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "caller.toml"
    profile.write_text(
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
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")


def test_regenerate_workspace_command_exists() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPTS / "agent_admin.py"), "engineer", "regenerate-workspace", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--all-seats" in result.stdout
    assert "--project" in result.stdout


def _handlers(tmp_path: Path):
    from agent_admin_crud import CrudHandlers

    hooks = MagicMock()
    hooks.error_cls = RuntimeError
    hooks.ensure_dir.side_effect = lambda path: Path(path).mkdir(parents=True, exist_ok=True)
    hooks.load_project.return_value = SimpleNamespace(name="install", engineers=["builder"])
    session = SimpleNamespace(
        engineer_id="builder",
        project="install",
        session="install-builder-codex",
        tool="codex",
        workspace=str(tmp_path / "workspace" / "builder"),
    )
    hooks.resolve_engineer_session.return_value = session
    hooks.render_template_text.return_value = {
        "AGENTS.md": "<!-- rendered_from_clawseat_sha=new rendered_at=now renderer_version=v1 -->\n# builder\nnew\n",
    }
    hooks.apply_template.side_effect = lambda _session, _project: (
        Path(session.workspace) / "AGENTS.md"
    ).write_text(hooks.render_template_text.return_value["AGENTS.md"], encoding="utf-8")
    return CrudHandlers(hooks), hooks, session


def test_regenerate_workspace_does_not_touch_session_toml(tmp_path: Path) -> None:
    handlers, hooks, session = _handlers(tmp_path)
    workspace = Path(session.workspace)
    workspace.mkdir(parents=True)
    (workspace / "AGENTS.md").write_text("# builder\nnew\n", encoding="utf-8")
    session_toml = tmp_path / "sessions" / "install" / "builder" / "session.toml"
    session_toml.parent.mkdir(parents=True)
    session_toml.write_text("session = 'install-builder-codex'\n", encoding="utf-8")

    rc = handlers.engineer_regenerate_workspace(
        SimpleNamespace(project="install", engineer="builder", all_seats=False, yes=True)
    )

    assert rc == 0
    assert session_toml.read_text(encoding="utf-8") == "session = 'install-builder-codex'\n"
    hooks.apply_template.assert_called_once()


def test_regenerate_workspace_creates_backup_before_overwrite(tmp_path: Path) -> None:
    handlers, _hooks, session = _handlers(tmp_path)
    workspace = Path(session.workspace)
    workspace.mkdir(parents=True)
    (workspace / "AGENTS.md").write_text("operator local edit\n", encoding="utf-8")

    handlers.engineer_regenerate_workspace(
        SimpleNamespace(project="install", engineer="builder", all_seats=False, yes=True)
    )

    backups = list(workspace.glob(".backup-*/AGENTS.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "operator local edit\n"
