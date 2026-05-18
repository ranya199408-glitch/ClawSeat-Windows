from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_SCRIPTS = Path(__file__).resolve().parents[1] / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agent_admin_switch import SwitchHandlers  # noqa: E402


def test_switch_harness_rejects_ark_provider_for_non_claude_tool() -> None:
    hooks = SimpleNamespace(
        error_cls=RuntimeError,
        legacy_secrets_root=Path("/tmp/legacy-secrets"),
        tool_binaries={"claude": "claude", "codex": "codex", "gemini": "gemini"},
        default_tool_args={"claude": [], "codex": [], "gemini": []},
        identity_name=lambda *args: "identity",
        runtime_dir_for_identity=lambda *args: Path("/tmp/runtime"),
        secret_file_for=lambda *args: Path("/tmp/secret.env"),
        session_name_for=lambda *args: "session",
        ensure_dir=lambda path: None,
        ensure_secret_permissions=lambda path: None,
        write_env_file=lambda *args, **kwargs: None,
        parse_env_file=lambda path: {},
        load_project=lambda project: SimpleNamespace(name=project),
        load_project_or_current=lambda project: SimpleNamespace(name=project or "install"),
        load_session=lambda project, engineer: SimpleNamespace(
            engineer_id=engineer,
            project=project,
            tool="gemini",
            auth_mode="api",
            provider="ark",
            identity="gemini.api.ark.install.planner",
            workspace="/tmp/workspace",
            runtime_dir="/tmp/runtime",
            session="install-planner-gemini",
            bin_path="gemini",
            monitor=False,
            legacy_sessions=[],
            launch_args=[],
            secret_file="/tmp/secret.env",
            wrapper="",
        ),
        write_session=lambda session: None,
        apply_template=lambda session, project: None,
        session_stop_engineer=lambda session: None,
        session_record_cls=SimpleNamespace,
        normalize_name=lambda name: name,
    )
    handlers = SwitchHandlers(hooks)

    with pytest.raises(RuntimeError, match="ark provider is claude-only"):
        handlers.session_switch_harness(
            SimpleNamespace(
                project="smoke02",
                engineer="planner",
                tool="gemini",
                mode="api",
                provider="ark",
                model="",
            )
        )
