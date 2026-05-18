from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from core.migration import dynamic_common
from core.tui import ancestor_brief


REPO = Path(__file__).resolve().parents[1]
LAUNCHERS = REPO / "core" / "launchers"
SCRIPTS = REPO / "core" / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _v2_profile(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                'version = 2',
                'profile_name = "install"',
                'template_name = "gstack-harness"',
                'project_name = "install"',
                f'repo_root = "{REPO}"',
                'tasks_root = "~/.agents/tasks/install"',
                'project_doc = "~/.agents/tasks/install/PROJECT.md"',
                'tasks_doc = "~/.agents/tasks/install/TASKS.md"',
                'status_doc = "~/.agents/tasks/install/STATUS.md"',
                f'send_script = "{REPO / "core" / "shell-scripts" / "send-and-verify.sh"}"',
                f'agent_admin = "{REPO / "core" / "scripts" / "agent_admin.py"}"',
                'workspace_root = "~/.agents/workspaces/install"',
                'handoff_dir = "~/.agents/tasks/install/patrol/handoffs"',
                '',
                'machine_services = ["memory"]',
                'openclaw_frontstage_agent = "yu"',
                'seats = ["ancestor", "planner"]',
                '',
                '[seat_overrides.ancestor]',
                'tool = "claude"',
                'auth_mode = "oauth_token"',
                'provider = "anthropic"',
                '',
                '[seat_overrides.planner]',
                'tool = "claude"',
                'auth_mode = "oauth_token"',
                'provider = "anthropic"',
                '',
                '[dynamic_roster]',
                'enabled = true',
                'bootstrap_seats = ["ancestor"]',
                'default_start_seats = ["ancestor", "planner"]',
            ]
        ),
        encoding="utf-8",
    )
    return path


def _harness_profile_without_session_root(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                'version = 1',
                'profile_name = "test-profile"',
                'template_name = "gstack-harness"',
                'project_name = "test-project"',
                f'repo_root = "{REPO}"',
                f'tasks_root = "{path.parent / "tasks"}"',
                f'project_doc = "{path.parent / "tasks" / "PROJECT.md"}"',
                f'tasks_doc = "{path.parent / "tasks" / "TASKS.md"}"',
                f'status_doc = "{path.parent / "tasks" / "STATUS.md"}"',
                'send_script = "/bin/echo"',
                'status_script = "/bin/echo"',
                'patrol_script = "/bin/echo"',
                'agent_admin = "/bin/echo"',
                f'workspace_root = "{path.parent / "workspaces"}"',
                f'handoff_dir = "{path.parent / "handoffs"}"',
                'heartbeat_owner = "koder"',
                'active_loop_owner = "planner"',
                'default_notify_target = "planner"',
                f'heartbeat_receipt = "{path.parent / "workspaces" / "koder" / "HEARTBEAT_RECEIPT.toml"}"',
                'seats = ["koder", "planner"]',
                'heartbeat_seats = ["koder"]',
                '',
                '[seat_roles]',
                'koder = "frontstage-supervisor"',
                'planner = "planner-dispatcher"',
                '',
                '[dynamic_roster]',
                'enabled = false',
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_ancestor_brief_defaults_to_real_home_under_sandbox(monkeypatch, tmp_path: Path) -> None:
    sandbox_home = tmp_path / "sandbox-home"
    real_home = tmp_path / "real-home"
    sandbox_home.mkdir()
    real_home.mkdir()
    profile = _v2_profile(tmp_path / "install-profile-dynamic.toml")

    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    monkeypatch.setattr(ancestor_brief, "_tmux_session_alive", lambda _: False)

    ctx = ancestor_brief.load_context_from_profile(project="install", profile_path=profile)

    assert ctx.openclaw_tenant_workspace == real_home / ".openclaw" / "workspace-yu"
    assert ancestor_brief._render_path(real_home / ".agents" / "tasks") == "~/.agents/tasks"

    written = ancestor_brief.write_brief(ctx)
    assert written == real_home / ".agents" / "tasks" / "install" / "patrol" / "handoffs" / "memory-bootstrap.md"


def test_launcher_discover_uses_real_home_override(monkeypatch, tmp_path: Path) -> None:
    sandbox_home = tmp_path / "sandbox-home"
    real_home = tmp_path / "real-home"
    sandbox_home.mkdir()
    real_home.mkdir()

    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))
    monkeypatch.delenv("AGENT_LAUNCHER_DISCOVER_HOME", raising=False)

    module = _load_module("issue15_launcher_discover", LAUNCHERS / "agent-launcher-discover.py")
    assert module.discover_home() == real_home


def test_seat_template_default_engineers_root_uses_real_home(monkeypatch, tmp_path: Path) -> None:
    sandbox_home = tmp_path / "sandbox-home"
    real_home = tmp_path / "real-home"
    sandbox_home.mkdir()
    real_home.mkdir()

    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))

    module = _load_module("issue15_seat_claude_template", SCRIPTS / "seat_claude_template.py")
    assert module.DEFAULT_ENGINEERS_ROOT == real_home / ".agents" / "engineers"


def test_dynamic_common_defaults_session_root_to_real_home(monkeypatch, tmp_path: Path) -> None:
    sandbox_home = tmp_path / "sandbox-home"
    real_home = tmp_path / "real-home"
    sandbox_home.mkdir()
    real_home.mkdir()

    monkeypatch.setenv("HOME", str(sandbox_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(real_home))

    profile = _harness_profile_without_session_root(tmp_path / "profile.toml")
    loaded = dynamic_common.load_profile(profile)

    assert loaded.session_root == real_home / ".agents" / "sessions"
