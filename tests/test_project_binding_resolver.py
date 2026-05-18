"""Tests for reverse lookup chat_id → project in core/lib/project_binding.py.

Koder uses `resolve_project_from_chat_id(chat_id)` at message-in time to
figure out which project a Feishu session belongs to. v0.4 A-track
enforces injective chat_id → project (one project per group); the
resolver must raise on collisions and return None on unknown chats.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))

import project_binding as pb  # noqa: E402


def _write_binding(tasks_root: Path, project: str, group_id: str) -> None:
    d = tasks_root / project
    d.mkdir(parents=True, exist_ok=True)
    (d / "PROJECT_BINDING.toml").write_text(
        "version = 1\n"
        f'project = "{project}"\n'
        f'feishu_group_id = "{group_id}"\n'
        'feishu_bot_account = "koder"\n'
        "require_mention = false\n"
        'bound_at = "2026-04-22T00:00:00+00:00"\n',
        encoding="utf-8",
    )


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    tasks = home / ".agents" / "tasks"
    tasks.mkdir(parents=True)
    # Use the env override recognised by real_home.real_user_home — this
    # survives cross-module import caching (install_wizard re-imports
    # project_binding, so a module-level monkeypatch doesn't always reach
    # it in certain ordering).
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(home))
    # Defensive: also patch the bound reference on pb for tests that call
    # pb.* directly.
    monkeypatch.setattr(pb, "real_user_home", lambda: home)
    return home


class TestResolveProjectFromChatId:

    def test_unknown_chat_returns_none(self, fake_home):
        _write_binding(fake_home / ".agents" / "tasks", "install",
                       "<FEISHU_GROUP_ID>")
        assert pb.resolve_project_from_chat_id("<FEISHU_GROUP_ID>") is None

    def test_empty_chat_id_returns_none(self, fake_home):
        _write_binding(fake_home / ".agents" / "tasks", "install",
                       "<FEISHU_GROUP_ID>")
        assert pb.resolve_project_from_chat_id("") is None
        assert pb.resolve_project_from_chat_id("   ") is None

    def test_single_match_returns_binding(self, fake_home):
        _write_binding(fake_home / ".agents" / "tasks", "install",
                       "<FEISHU_GROUP_ID>")
        got = pb.resolve_project_from_chat_id("<FEISHU_GROUP_ID>")
        assert got is not None
        assert got.project == "install"
        assert got.feishu_group_id == "<FEISHU_GROUP_ID>"

    def test_distinct_chats_resolve_distinct_projects(self, fake_home):
        root = fake_home / ".agents" / "tasks"
        _write_binding(root, "install", "<FEISHU_GROUP_ID>")
        _write_binding(root, "cartooner", "<FEISHU_GROUP_ID>")
        _write_binding(root, "audit", "<FEISHU_GROUP_ID>")
        assert pb.resolve_project_from_chat_id(
            "<FEISHU_GROUP_ID>"
        ).project == "install"
        assert pb.resolve_project_from_chat_id(
            "<FEISHU_GROUP_ID>"
        ).project == "cartooner"
        assert pb.resolve_project_from_chat_id(
            "<FEISHU_GROUP_ID>"
        ).project == "audit"

    def test_duplicate_chat_ids_raise(self, fake_home):
        root = fake_home / ".agents" / "tasks"
        same = "<FEISHU_GROUP_ID>"
        _write_binding(root, "install", same)
        _write_binding(root, "cartooner", same)
        with pytest.raises(pb.ProjectBindingError) as exc_info:
            pb.resolve_project_from_chat_id(same)
        msg = str(exc_info.value)
        assert "install" in msg and "cartooner" in msg
        assert "one project per" in msg.lower()


class TestChatIdIndex:

    def test_empty_when_no_projects(self, fake_home):
        assert pb.chat_id_index() == {}

    def test_round_trip_all_bindings(self, fake_home):
        root = fake_home / ".agents" / "tasks"
        _write_binding(root, "install", "<FEISHU_GROUP_ID>")
        _write_binding(root, "cartooner", "<FEISHU_GROUP_ID>")
        idx = pb.chat_id_index()
        assert idx == {
            "<FEISHU_GROUP_ID>": "install",
            "<FEISHU_GROUP_ID>": "cartooner",
        }

    def test_duplicate_detection_on_build(self, fake_home):
        root = fake_home / ".agents" / "tasks"
        same = "<FEISHU_GROUP_ID>"
        _write_binding(root, "alpha", same)
        _write_binding(root, "beta", same)
        with pytest.raises(pb.ProjectBindingError):
            pb.chat_id_index()

    def test_skips_projects_without_group_id(self, fake_home, tmp_path):
        root = fake_home / ".agents" / "tasks"
        _write_binding(root, "install", "<FEISHU_GROUP_ID>")
        # empty-group-id project must not pollute the index
        blank_project = root / "blank"
        blank_project.mkdir(parents=True, exist_ok=True)
        (blank_project / "PROJECT_BINDING.toml").write_text(
            'version = 1\nproject = "blank"\nfeishu_group_id = ""\n',
            encoding="utf-8",
        )
        idx = pb.chat_id_index()
        assert idx == {"<FEISHU_GROUP_ID>": "install"}

