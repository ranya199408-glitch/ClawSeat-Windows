"""Tests for core/skills/planner/scripts/install_planner_hook.py."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "skills" / "planner" / "scripts" / "install_planner_hook.py"
_HOOK = _REPO / "scripts" / "hooks" / "planner-stop-hook.sh"


def _load_module():
    spec = importlib.util.spec_from_file_location("install_planner_hook", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dry_run_prints_target_without_writing(tmp_path: Path) -> None:
    workspace = tmp_path / "planner"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--workspace",
            str(workspace),
            "--clawseat-root",
            str(_REPO),
            "--dry-run",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "target:" in proc.stdout
    assert not (workspace / ".claude" / "settings.json").exists()


def test_install_planner_hook_adds_entry_and_is_idempotent(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "planner"
    settings_path, settings, changed = module.install_planner_hook(workspace, _HOOK)
    assert changed is True
    assert settings_path == workspace / ".claude" / "settings.json"
    rendered = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(rendered, encoding="utf-8")

    settings_path_2, settings_2, changed_2 = module.install_planner_hook(workspace, _HOOK)
    assert settings_path_2 == settings_path
    assert changed_2 is False
    stop_entries = settings_2["hooks"]["Stop"]
    assert len(stop_entries) == 1
    hook_def = stop_entries[0]["hooks"][0]
    assert hook_def["command"] == f"bash {_HOOK}"
    assert hook_def["timeout"] == 10


def test_install_planner_hook_preserves_existing_hooks(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "planner"
    settings_path = workspace / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "matcher": "foo",
                            "hooks": [{"type": "command", "command": "bash /tmp/keep.sh", "timeout": 5}],
                        }
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _, settings, changed = module.install_planner_hook(workspace, _HOOK)
    assert changed is True
    stop_entries = settings["hooks"]["Stop"]
    assert len(stop_entries) == 2
    assert stop_entries[0]["hooks"][0]["command"] == "bash /tmp/keep.sh"
