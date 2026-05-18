from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_install_isolation_helpers_modular", _HELPERS_PATH
)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root


def test_install_modules_keep_expected_exports() -> None:
    lib_dir = _REPO / "scripts" / "install" / "lib"
    assert {path.name for path in lib_dir.glob("*.sh")} == {
        "detect.sh",
        "i18n.sh",
        "preflight.sh",
        "provider.sh",
        "project.sh",
        "secrets.sh",
        "self_update.sh",
        "skills.sh",
        "window.sh",
    }

    expected_exports = {
        "detect.sh": ["detect_oauth_states", "detect_pty_resource", "detect_all"],
        "i18n.sh": ["i18n_set", "i18n_get"],
        "preflight.sh": ["ensure_host_deps", "scan_machine"],
        "provider.sh": ["detect_provider", "select_provider", "write_provider_env"],
        "project.sh": ["bootstrap_project_profile", "migrate_project_profile_to_v2", "write_project_local_toml"],
        "secrets.sh": ["seed_bootstrap_secrets", "ensure_privacy_kb_template"],
        "self_update.sh": ["self_update_check", "prompt_autoupdate_optin"],
        "skills.sh": ["install_skills_by_tier", "install_skill_tier_for_home"],
        "window.sh": ["workers_payload", "memories_payload", "open_iterm_window"],
    }
    for module, functions in expected_exports.items():
        text = (lib_dir / module).read_text(encoding="utf-8")
        for function in functions:
            assert f"{function}()" in text

    install_text = (_REPO / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert 'source "$INSTALL_LIB_DIR/$_install_lib_module"' in install_text
    for flag in (
        "--reinstall",
        "--force",
        "--provider",
        "--memory-tool",
        "--memory-model",
        "--all-api-provider",
        "--uninstall",
        "--enable-auto-patrol",
        "--load-all-skills",
        "--dry-run",
        "--detect-only",
        "--reset-harness-memory",
        "--base-url",
        "--api-key",
    ):
        assert flag in install_text


def _install_env(tmp_path: Path, home: Path, py_stubs: Path, launcher_log: Path, tmux_log: Path) -> dict[str, str]:
    return {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        "PYTHON_BIN": sys.executable,
        "LOG_FILE": str(launcher_log),
        "TMUX_LOG_FILE": str(tmux_log),
    }


def test_install_modular_dry_run_passes(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    env = _install_env(tmp_path, home, py_stubs, launcher_log, tmux_log)
    for args in (
        ["--project", "modular-dry", "--dry-run"],
        ["--reinstall", "modular-dry", "--dry-run"],
    ):
        result = subprocess.run(
            ["bash", str(root / "scripts" / "install.sh"), *args],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            check=False,
        )

        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "Project: modular-dry" in combined
        assert "Step 7a: open per-project workers window" in combined
        assert "agent-launcher.sh" in combined


def test_install_lib_source_resolution(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    cwd = tmp_path / "arbitrary-cwd"
    cwd.mkdir()
    probe = f"""
set -euo pipefail
source "{root / 'scripts' / 'install.sh'}"
[[ "$SCRIPT_DIR" == "{root / 'scripts'}" ]]
[[ "$INSTALL_LIB_DIR" == "{root / 'scripts' / 'install' / 'lib'}" ]]
declare -F parse_args >/dev/null
declare -F self_update_check >/dev/null
declare -F ensure_host_deps >/dev/null
declare -F select_provider >/dev/null
declare -F bootstrap_project_profile >/dev/null
declare -F seed_bootstrap_secrets >/dev/null
declare -F install_skills_by_tier >/dev/null
declare -F workers_payload >/dev/null
"""
    result = subprocess.run(
        ["bash", "-c", probe],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        env=_install_env(tmp_path, home, py_stubs, launcher_log, tmux_log),
        check=False,
    )

    assert result.returncode == 0, result.stderr
