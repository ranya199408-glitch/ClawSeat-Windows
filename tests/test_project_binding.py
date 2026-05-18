"""C2 tests: PROJECT_BINDING.toml as the per-project SSOT."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
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
    # Re-import so module-level path resolution picks up the override.
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


# ── Schema / validation ────────────────────────────────────────────────


def test_validate_feishu_group_id_accepts_canonical():
    pb = _load_pb()
    assert pb.validate_feishu_group_id("<FEISHU_GROUP_ID>") == \
        "<FEISHU_GROUP_ID>"


def test_validate_feishu_group_id_rejects_garbage():
    pb = _load_pb()
    # Each value is already-trimmed; validator strips and then shape-matches.
    for bad in ("", "test-group", "group-123", "oc_", "oc bad", "OC_FOO"):
        with pytest.raises(pb.ProjectBindingError):
            pb.validate_feishu_group_id(bad)


def test_validate_project_name_rejects_bad():
    pb = _load_pb()
    for bad in ("", "  ", "..", "/abs", "proj/subproject", "-leading-dash"):
        with pytest.raises(pb.ProjectBindingError):
            pb.validate_project_name(bad)


# ── Write / read round-trip ────────────────────────────────────────────


def test_bind_and_load_round_trip(_isolated_home, monkeypatch):
    pb = _load_pb()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        path = pb.bind_project(
            project="install",
            feishu_group_id="",
            feishu_bot_account="koder",
            require_mention=False,
            bound_by="ywf",
        )
        assert path.exists()
        assert path.name == "PROJECT_BINDING.toml"
        assert path.parent == _isolated_home / ".agents" / "tasks" / "install"

        binding = pb.load_binding("install")
    assert binding is not None
    assert binding.project == "install"
    assert binding.feishu_group_id == "<FEISHU_GROUP_ID>"
    assert binding.feishu_bot_account == "koder"
    assert binding.require_mention is False
    assert binding.bound_by == "ywf"
    assert binding.bound_at  # auto-filled timestamp


def test_load_returns_none_for_missing(_isolated_home):
    pb = _load_pb()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        assert pb.load_binding("nope") is None


def test_load_refuses_cross_project_binding(_isolated_home):
    """A PROJECT_BINDING.toml whose declared `project` disagrees with the
    directory it lives in is a misconfiguration — must raise, not silently
    succeed with the wrong answer."""
    pb = _load_pb()
    target = _isolated_home / ".agents" / "tasks" / "install" / "PROJECT_BINDING.toml"
    target.parent.mkdir(parents=True)
    target.write_text(
        'project = "cartooner"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
    )
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        with pytest.raises(pb.ProjectBindingError) as exc_info:
            pb.load_binding("install")
    assert "install" in str(exc_info.value)
    assert "cartooner" in str(exc_info.value)


def test_rewrite_preserves_extra_keys(_isolated_home):
    """Future schema fields must not be dropped on rewrite."""
    pb = _load_pb()
    target = _isolated_home / ".agents" / "tasks" / "install" / "PROJECT_BINDING.toml"
    target.parent.mkdir(parents=True)
    target.write_text(
        'project = "install"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'custom_label = "smoke-run"\n'
        'custom_counter = 42\n'
    )
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        binding = pb.load_binding("install")
        assert binding is not None
        assert binding.extras == {"custom_label": "smoke-run", "custom_counter": 42}
        pb.write_binding(binding)
        re_read = pb.load_binding("install")
    assert re_read is not None
    assert re_read.extras == {"custom_label": "smoke-run", "custom_counter": 42}


def test_list_bindings_enumerates_directories(_isolated_home):
    pb = _load_pb()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        pb.bind_project(project="install", feishu_group_id="")
        pb.bind_project(project="cartooner", feishu_group_id="")
        # Garbage directory that is NOT a binding — must be ignored silently.
        (_isolated_home / ".agents" / "tasks" / "not-a-project").mkdir()
        bindings = pb.list_bindings()
    assert {b.project for b in bindings} == {"install", "cartooner"}


# ── Integration with _feishu.resolve_feishu_group_strict ──────────────


def test_feishu_strict_reads_project_binding(_isolated_home):
    """End-to-end: writing a binding via the library makes the strict
    resolver pick it up as source=project_binding."""
    pb = _load_pb()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        pb.bind_project(
            project="install", feishu_group_id="",
        )
        feishu = _load_feishu()
        group_id, source = feishu.resolve_feishu_group_strict("install")
    assert group_id == "<FEISHU_GROUP_ID>"
    assert source.startswith("project_binding:")


def test_feishu_strict_without_binding_still_errors(_isolated_home):
    """A newly-created project with no binding and no contract must still
    fail — binding is the preferred source but not the only source."""
    _load_pb()  # ensure path is populated
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        feishu = _load_feishu()
        with pytest.raises(feishu.FeishuGroupResolutionError):
            feishu.resolve_feishu_group_strict("no-such-project")


# ── R6-K2: feishu_group_name + feishu_external enrichment ─────────────


_MOCK_CHATS_JSON = json.dumps({
    "code": 0,
    "data": {
        "has_more": False,
        "items": [
            {
                "chat_id": "<FEISHU_GROUP_ID>",
                "name": "Install Squad",
                "external": False,
            },
            {
                "chat_id": "<FEISHU_GROUP_ID>",
                "name": "Other Group",
                "external": True,
            },
        ],
    },
})


def test_bind_populates_feishu_group_metadata_from_lark_cli(_isolated_home):
    """fetch_chat_metadata + bind_project write feishu_group_name and
    feishu_external into PROJECT_BINDING.toml from mocked lark-cli output."""
    pb = _load_pb()
    with mock.patch("pwd.getpwuid") as m_pwd, \
         mock.patch("project_binding.shutil.which", return_value="/usr/bin/lark-cli"), \
         mock.patch("project_binding.subprocess.run") as m_run:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        m_run.return_value = mock.Mock(returncode=0, stdout=_MOCK_CHATS_JSON, stderr="")

        group_name, group_external = pb.fetch_chat_metadata("<FEISHU_GROUP_ID>")
        path = pb.bind_project(
            project="install",
            feishu_group_id="",
            feishu_group_name=group_name,
            feishu_external=group_external,
        )

    assert group_name == "Install Squad"
    assert group_external is False

    binding = pb.load_binding("install")
    assert binding is not None
    assert binding.feishu_group_name == "Install Squad"
    assert binding.feishu_external is False

    toml_text = path.read_text()
    assert 'feishu_group_name = "Install Squad"' in toml_text
    assert "feishu_external = false" in toml_text


def test_fetch_chat_metadata_returns_empty_when_lark_cli_missing(_isolated_home):
    pb = _load_pb()
    with mock.patch("project_binding.shutil.which", return_value=None):
        name, external = pb.fetch_chat_metadata("<FEISHU_GROUP_ID>")
    assert name == ""
    assert external is False


def test_fetch_chat_metadata_returns_empty_when_group_not_found(_isolated_home):
    pb = _load_pb()
    with mock.patch("project_binding.shutil.which", return_value="/usr/bin/lark-cli"), \
         mock.patch("project_binding.subprocess.run") as m_run:
        m_run.return_value = mock.Mock(returncode=0, stdout=_MOCK_CHATS_JSON, stderr="")
        name, external = pb.fetch_chat_metadata("<FEISHU_GROUP_ID>")
    assert name == ""
    assert external is False


def test_bind_backward_compat_missing_new_fields(_isolated_home):
    """Existing PROJECT_BINDING.toml without the new fields loads without error."""
    pb = _load_pb()
    target = _isolated_home / ".agents" / "tasks" / "legacy" / "PROJECT_BINDING.toml"
    target.parent.mkdir(parents=True)
    target.write_text(
        'version = 1\n'
        'project = "legacy"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n'
        'feishu_bot_account = "koder"\n'
        'require_mention = false\n'
        'bound_at = "2026-01-01T00:00:00+00:00"\n',
        encoding="utf-8",
    )
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_isolated_home))
        binding = pb.load_binding("legacy")
    assert binding is not None
    assert binding.feishu_group_name == ""
    assert binding.feishu_external is False
