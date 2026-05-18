"""Tests for dynamic PENDING_SEATS resolution from template.

Verifies that install.sh reads seat list from template TOML instead of
hardcoding.

clawseat-creative template deprecated 2026-05-02 (BV-2); creative-specific tests removed.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"

_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_install_isolation_helpers_pending_seats", _HELPERS_PATH
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root


def _run_install(root, home, launcher_log, tmux_log, py_stubs, extra_args):
    args = list(extra_args)
    if "--provider" not in args and "--base-url" not in args:
        args.extend(["--provider", "1"])
    result = subprocess.run(
        ["bash", str(root / "scripts" / "install.sh")] + args,
        input="\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": sys.executable,
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
            "CLAWSEAT_TRUST_PROMPT_SLEEP_SECONDS": "0",
        },
        check=False,
    )
    return result


def _copy_templates(root):
    """Copy repo-level templates/ into fake root so resolve_pending_seats() can find them."""
    src = _REPO / "templates"
    dst = root / "templates"
    if src.exists():
        shutil.copytree(str(src), str(dst), dirs_exist_ok=True)


# creative template tests removed — template deprecated 2026-05-02 (BV-2)

def test_engineering_patrol_seat_gets_template_model(tmp_path):
    """clawseat-engineering: patrol (claude/api/minimax) override must carry model = MiniMax-M2.7-highspeed
    from the template TOML, not the ancestor's selected model."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    _copy_templates(root)

    # Use anthropic provider for ancestor; patrol seat should still get its own model.
    result = _run_install(root, home, launcher_log, tmux_log, py_stubs,
                          ["--project", "engmodeltest", "--template", "clawseat-engineering"])
    assert result.returncode == 0, result.stderr

    local_toml = home / ".agents" / "tasks" / "engmodeltest" / "project-local.toml"
    assert local_toml.exists()
    content = local_toml.read_text(encoding="utf-8")

    lines = content.splitlines()
    in_patrol = False
    patrol_lines: list[str] = []
    for line in lines:
        if "[[overrides]]" in line:
            in_patrol = False
        if 'id = "patrol"' in line:
            in_patrol = True
        if in_patrol:
            patrol_lines.append(line)

    patrol_text = "\n".join(patrol_lines)
    assert "MiniMax-M2.7-highspeed" in patrol_text, (
        f"patrol override must carry template-specified model MiniMax-M2.7-highspeed:\n{patrol_text}"
        f"\n\nFull TOML:\n{content}"
    )


def test_engineering_template_seat_order_includes_reviewer(tmp_path):
    """clawseat-engineering project-local.toml has the 5-seat engineering roster (designer removed BV-1)."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    _copy_templates(root)

    result = _run_install(root, home, launcher_log, tmux_log, py_stubs,
                          ["--project", "testengineering", "--template", "clawseat-engineering"])
    assert result.returncode == 0, result.stderr

    local_toml = home / ".agents" / "tasks" / "testengineering" / "project-local.toml"
    assert local_toml.exists()
    content = local_toml.read_text(encoding="utf-8")

    assert 'seat_order = ["memory", "planner", "builder", "reviewer", "patrol"]' in content
