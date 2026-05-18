"""FR-4: install.sh menu renders (model: ...) annotation and Project: header.

Tests verify:
1. ``--dry-run`` output includes ``Project:`` line (all paths).
2. Interactive provider selection menu (non-dry-run with detected candidates)
   includes ``(model: ...)`` annotation and ``Project:`` header.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_install_isolation_helpers_menu", _HELPERS_PATH
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_write_executable = _HELPERS._write_executable

_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"


def _run_install(
    tmp_path: Path,
    *,
    extra_args: list[str],
    stdin_input: str = "",
    extra_env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run install.sh from a fake root and return the CompletedProcess."""
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        "PYTHON_BIN": sys.executable,
        "LOG_FILE": str(launcher_log),
        "TMUX_LOG_FILE": str(tmux_log),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"), *extra_args],
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
        check=False,
    )


def test_dry_run_prints_project_header(tmp_path: Path) -> None:
    """--dry-run must always print 'Project: <name>' regardless of candidates."""
    result = _run_install(
        tmp_path,
        extra_args=["--dry-run", "--project", "myproject"],
    )
    assert result.returncode == 0, (
        f"install.sh --dry-run failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    assert "Project: myproject" in combined, (
        f"'Project: myproject' not found in output.\nCombined:\n{combined}"
    )


def test_dry_run_default_project_is_install(tmp_path: Path) -> None:
    """Non-TTY dry-run without project/template flags fails before the menu."""
    result = _run_install(
        tmp_path,
        extra_args=["--dry-run"],
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "NON_TTY_NO_TEMPLATE" in combined
    assert "--template" in combined


def test_interactive_menu_renders_model_and_project(tmp_path: Path) -> None:
    """Detected candidates still render Project/model before non-TTY guard stops.

    The fake scan script (from _fake_install_root) emits a MINIMAX_API_KEY so
    detect_provider() finds a minimax candidate. Z2 then rejects scripted stdin
    and requires --provider in non-TTY runs.
    """
    result = _run_install(
        tmp_path,
        extra_args=["--project", "menutest"],
        stdin_input="1\n",
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "Project: menutest" in combined, (
        f"'Project: menutest' not found in menu output.\nCombined:\n{combined}"
    )
    assert "model:" in combined, (
        f"'model:' annotation not found in menu output.\nCombined:\n{combined}"
    )
    assert "NON_TTY_NO_PROVIDER" in combined


def test_interactive_menu_model_value_is_correct_for_minimax(tmp_path: Path) -> None:
    """The minimax model shown before the non-TTY stop matches provider_default_model()."""
    import sys as _sys
    _sys.path.insert(0, str(_REPO / "core" / "scripts"))
    from agent_admin_config import provider_default_model  # noqa: PLC0415

    expected_model = provider_default_model("claude", "minimax") or ""
    assert expected_model, "provider_default_model('claude', 'minimax') must not be empty"

    result = _run_install(
        tmp_path,
        extra_args=["--project", "modelcheck"],
        stdin_input="1\n",
    )
    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert f"model: {expected_model}" in combined, (
        f"Expected 'model: {expected_model}' in output but not found.\nCombined:\n{combined}"
    )
    assert "NON_TTY_NO_PROVIDER" in combined
