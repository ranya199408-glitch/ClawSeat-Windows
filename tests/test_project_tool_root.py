from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    for name in ("project_tool_root", "project_binding", "real_home"):
        sys.modules.pop(name, None)
    yield tmp_path


def _load_module():
    import project_tool_root

    importlib.reload(project_tool_root)
    return project_tool_root


def test_project_tool_root_anchors_under_agent_runtime(tmp_path):
    module = _load_module()

    root = module.project_tool_root("install")
    assert root == tmp_path / ".agent-runtime" / "projects" / "install"


def test_project_tool_subpath_resolves_children(tmp_path):
    module = _load_module()

    path = module.project_tool_subpath("install", "Library/Application Support/iTerm2")
    assert path == (
        tmp_path / ".agent-runtime" / "projects" / "install" / "Library" / "Application Support" / "iTerm2"
    )

