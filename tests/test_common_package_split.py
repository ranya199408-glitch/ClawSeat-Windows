from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_SCRIPTS = REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts"


def _fresh_common():
    sys.path.insert(0, str(HARNESS_SCRIPTS))
    for name in list(sys.modules):
        if name == "_common" or name.startswith("_common."):
            sys.modules.pop(name, None)
    return importlib.import_module("_common")


def test_common_package_backward_compat_import():
    common = _fresh_common()
    namespace: dict[str, object] = {}
    exec("from _common import *", namespace)

    for name in (
        "HarnessProfile",
        "load_profile",
        "notify",
        "heartbeat_manifest_path",
        "session_name_for",
        "expand_profile_value",
        "write_todo",
        "heartbeat_state",
        "_patch_claude_settings_from_profile",
    ):
        assert hasattr(common, name)
        assert name in namespace

    shim_path = HARNESS_SCRIPTS / "_common.py"
    spec = importlib.util.spec_from_file_location("common_shim_test", shim_path)
    shim = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = shim
    spec.loader.exec_module(shim)
    assert callable(shim.notify)
    assert hasattr(shim, "_patch_claude_settings_from_profile")


def test_harness_profile_loads_from_package(tmp_path: Path):
    common = _fresh_common()
    profile_path = tmp_path / "profile.toml"
    tasks_root = tmp_path / "tasks"
    profile_path.write_text(
        "\n".join(
            [
                'profile_name = "demo.dynamic"',
                'template_name = "clawseat-engineering"',
                'project_name = "demo"',
                f'repo_root = "{tmp_path}"',
                f'tasks_root = "{tasks_root}"',
                f'project_doc = "{tasks_root / "PROJECT.md"}"',
                f'tasks_doc = "{tasks_root / "TASKS.md"}"',
                f'status_doc = "{tasks_root / "STATUS.md"}"',
                f'send_script = "{tmp_path / "send.sh"}"',
                f'agent_admin = "{tmp_path / "agent_admin.py"}"',
                f'workspace_root = "{tmp_path / "workspaces"}"',
                f'handoff_dir = "{tasks_root / "patrol" / "handoffs"}"',
                'seats = ["memory", "planner", "builder"]',
                'heartbeat_seats = ["memory"]',
                "",
                "[seat_roles]",
                'memory = "memory"',
                'planner = "planner"',
                'builder = "builder"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    profile = common.load_profile(profile_path)

    assert isinstance(profile, common.HarnessProfile)
    assert profile.project_name == "demo"
    assert profile.declared_project_seats() == ["memory", "planner", "builder"]
