from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "scripts"))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in list(sys.modules):
        if name in {
            "agent_admin",
            "agent_admin_config",
            "agent_admin_crud",
            "agent_admin_parser",
            "agent_admin_session",
            "project_binding",
            "project_tool_root",
            "real_home",
        }:
            sys.modules.pop(name, None)
    yield tmp_path


def _load_pb():
    import project_binding

    importlib.reload(project_binding)
    return project_binding


def _load_agent_admin():
    import agent_admin

    importlib.reload(agent_admin)
    return agent_admin


def _load_session():
    import agent_admin_session

    importlib.reload(agent_admin_session)
    return agent_admin_session


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_service = _HELPERS._make_service
_make_session = _HELPERS._make_session


def test_v1_binding_loads_as_v3_with_defaults() -> None:
    pb = _load_pb()
    path = Path(pb.bindings_root()) / "install" / "PROJECT_BINDING.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'version = 1\n'
        'project = "install"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'bound_at = "2026-04-22T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    binding = pb.load_binding("install")

    assert binding is not None
    assert binding.version == 3
    assert binding.feishu_group_id == "<FEISHU_GROUP_ID>"
    assert binding.tools_isolation == "shared-real-home"
    assert binding.gemini_account_email == ""
    assert binding.codex_account_email == ""
    assert binding.feishu_sender_mode == "auto"


def test_v2_binding_loads_as_v3_preserving_fields() -> None:
    pb = _load_pb()
    path = Path(pb.bindings_root()) / "install" / "PROJECT_BINDING.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'version = 2\n'
        'project = "install"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'feishu_sender_app_id = "<FEISHU_APP_ID>"\n'
        'feishu_sender_mode = "user"\n'
        'openclaw_koder_agent = "yu"\n'
        'require_mention = true\n'
        'bound_at = "2026-04-22T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    binding = pb.load_binding("install")

    assert binding is not None
    assert binding.version == 3
    assert binding.feishu_sender_app_id == "<FEISHU_APP_ID>"
    assert binding.feishu_sender_mode == "user"
    assert binding.openclaw_koder_agent == "yu"
    assert binding.require_mention is True
    assert binding.tools_isolation == "shared-real-home"


def test_per_project_binding_without_tool_root_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pb = _load_pb()
    pb.bind_project(
        project="smoke01",
        feishu_group_id="",
        tools_isolation="per-project",
    )
    session = _make_session(
        tmp_path,
        engineer_id="planner-1",
        tool="claude",
        auth_mode="api",
        provider="minimax",
        secret_content="ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n",
    )
    session.project = "smoke01"
    svc, _hooks = _make_service(tmp_path, session)
    aas = _load_session()

    with (
        patch.object(aas.subprocess, "run", return_value=subprocess.CompletedProcess(["bash"], 0, "", "")),
        patch.object(svc, "_assert_session_running"),
        patch.object(svc, "_run_tmux_with_retry"),
        patch.object(svc, "_configure_session_display"),
    ):
        svc.start_engineer(session)

    err = capsys.readouterr().err
    assert "project tool root missing for smoke01" in err
    assert "agent_admin project init-tools smoke01 --from real-home" in err


def test_bootstrap_rebind_preserves_isolation_fields() -> None:
    pb = _load_pb()
    agent_admin = _load_agent_admin()
    pb.bind_project(
        project="install",
        feishu_group_id="",
        tools_isolation="per-project",
        gemini_account_email="gemini@example.com",
        codex_account_email="codex@example.com",
    )

    with patch("project_binding.fetch_chat_metadata", return_value=("Install Squad", False)):
        rc = agent_admin.cmd_project_bind(
            SimpleNamespace(
                project="install",
                feishu_group="<FEISHU_GROUP_ID>",
                feishu_sender_app_id="",
                feishu_sender_mode="auto",
                openclaw_koder_agent="",
                feishu_bot_account=None,
                require_mention=True,
                bound_by="ancestor",
            )
        )

    binding = _load_pb().load_binding("install")
    assert rc == 0
    assert binding is not None
    assert binding.feishu_group_id == "<FEISHU_GROUP_ID>"
    assert binding.tools_isolation == "per-project"
    assert binding.gemini_account_email == "gemini@example.com"
    assert binding.codex_account_email == "codex@example.com"
