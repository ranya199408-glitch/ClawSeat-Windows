"""C2 tests: PROJECT_BINDING.toml as the per-project SSOT."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    for key in ("CLAWSEAT_FEISHU_GROUP_ID", "OPENCLAW_FEISHU_GROUP_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    for name in ("project_binding", "real_home", "_feishu", "_utils"):
        sys.modules.pop(name, None)
    yield tmp_path


def _load_pb():
    import project_binding

    importlib.reload(project_binding)
    return project_binding


def _load_feishu():
    import _feishu

    importlib.reload(_feishu)
    return _feishu


def _load_agent_admin():
    import agent_admin

    importlib.reload(agent_admin)
    return agent_admin


def test_v3_write_emits_new_fields_and_omits_legacy_alias():
    pb = _load_pb()
    binding = pb.ProjectBinding(
        project="install",
        feishu_group_id="",
        feishu_sender_app_id="<FEISHU_APP_ID>",
        feishu_sender_mode="bot",
        openclaw_koder_agent="yu",
        tools_isolation="per-project",
        gemini_account_email="gemini@example.com",
        codex_account_email="codex@example.com",
        require_mention=True,
        bound_by="ancestor",
    )

    text = binding.as_toml()

    assert "version = 3" in text
    assert 'feishu_sender_app_id = "<FEISHU_APP_ID>"' in text
    assert 'feishu_sender_mode = "bot"' in text
    assert 'openclaw_koder_agent = "yu"' in text
    assert 'tools_isolation = "per-project"' in text
    assert 'gemini_account_email = "gemini@example.com"' in text
    assert 'codex_account_email = "codex@example.com"' in text
    assert "feishu_bot_account" not in text
    assert binding.feishu_bot_account == "<FEISHU_APP_ID>"


def test_legacy_bot_account_cli_maps_to_sender_app_id():
    pb = _load_pb()
    target = Path(pb.bindings_root()) / "install" / "PROJECT_BINDING.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        'version = 1\n'
        'project = "install"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'feishu_bot_account = "<FEISHU_APP_ID>"\n'
        'bound_at = "2026-04-22T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    binding = pb.load_binding("install")

    assert binding is not None
    assert binding.version == 3
    assert binding.feishu_sender_app_id == "<FEISHU_APP_ID>"
    assert binding.openclaw_koder_agent == ""
    assert binding.feishu_bot_account == "<FEISHU_APP_ID>"
    assert binding.tools_isolation == "shared-real-home"
    assert binding.gemini_account_email == ""
    assert binding.codex_account_email == ""


def test_legacy_bot_account_non_cli_maps_to_openclaw_koder_agent():
    pb = _load_pb()
    target = Path(pb.bindings_root()) / "install" / "PROJECT_BINDING.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        'version = 1\n'
        'project = "install"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'feishu_bot_account = "yu"\n'
        'bound_at = "2026-04-22T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    binding = pb.load_binding("install")

    assert binding is not None
    assert binding.version == 3
    assert binding.feishu_sender_app_id == ""
    assert binding.openclaw_koder_agent == "yu"
    assert binding.feishu_bot_account == "yu"
    assert binding.tools_isolation == "shared-real-home"


def test_invalid_tools_isolation_is_rejected():
    pb = _load_pb()
    target = Path(pb.bindings_root()) / "install" / "PROJECT_BINDING.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        'version = 3\n'
        'project = "install"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'tools_isolation = "banana"\n'
        'bound_at = "2026-04-22T00:00:00+00:00"\n',
        encoding="utf-8",
    )

    with pytest.raises(pb.ProjectBindingError, match="invalid tools_isolation"):
        pb.load_binding("install")


def test_parser_exposes_new_project_commands_and_deprecated_cli_alias(capsys):
    agent_admin = _load_agent_admin()
    parser = agent_admin.build_parser()

    parsed_init = parser.parse_args([
        "project",
        "init-tools",
        "install",
        "--from",
        "real-home",
        "--tools",
        "lark-cli,gemini",
    ])
    assert parsed_init.project == "install"
    assert parsed_init.from_source == "real-home"
    assert parsed_init.tools == "lark-cli,gemini"

    parsed_switch = parser.parse_args([
        "project",
        "switch-identity",
        "install",
        "--tool",
        "feishu",
        "--identity",
        "<FEISHU_APP_ID>",
    ])
    assert parsed_switch.tool == "feishu"
    assert parsed_switch.identity == "<FEISHU_APP_ID>"

    parsed_bind = parser.parse_args([
        "project",
        "bind",
        "--project",
        "install",
        "--feishu-group",
        "<FEISHU_GROUP_ID>",
        "--feishu-sender-app-id",
        "<FEISHU_APP_ID>",
        "--feishu-sender-mode",
        "user",
        "--openclaw-koder-agent",
        "yu",
    ])

    assert parsed_bind.feishu_sender_app_id == "<FEISHU_APP_ID>"
    assert parsed_bind.feishu_sender_mode == "user"
    assert parsed_bind.openclaw_koder_agent == "yu"
    assert parsed_bind.feishu_bot_account is None

    legacy = parser.parse_args([
        "project",
        "bind",
        "--project",
        "install",
        "--feishu-group",
        "<FEISHU_GROUP_ID>",
        "--feishu-bot-account",
        "<FEISHU_APP_ID>",
    ])

    assert legacy.feishu_bot_account == "<FEISHU_APP_ID>"

    with mock.patch("project_binding.fetch_chat_metadata", return_value=("Install Squad", False)):
        rc = agent_admin.cmd_project_bind(
            SimpleNamespace(
                project="install",
                feishu_group="<FEISHU_GROUP_ID>",
                feishu_sender_app_id="",
                feishu_sender_mode="auto",
                openclaw_koder_agent="",
                feishu_bot_account="<FEISHU_APP_ID>",
                require_mention=True,
                bound_by="ancestor",
            )
        )

    captured = capsys.readouterr()
    assert rc == 0
    assert "warning: --feishu-bot-account is deprecated" in captured.err

    binding = _load_pb().load_binding("install")
    assert binding is not None
    assert binding.feishu_sender_app_id == "<FEISHU_APP_ID>"
    assert binding.openclaw_koder_agent == ""
    assert binding.feishu_sender_mode == "auto"
    assert binding.feishu_group_id == "<FEISHU_GROUP_ID>"
