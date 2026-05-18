from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_python_select", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root
_write_executable = _HELPERS._write_executable


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHON_BIN", None)
    return env


def _write_bad_python3(path: Path, bad_log: Path) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ \"${1:-}\" == \"-c\" ]]; then\n'
        "  printf '3.9.6\\n'\n"
        "  exit 0\n"
        "fi\n"
        f"printf '%s\\n' \"$*\" >> {bad_log!s}\n"
        "printf '%s\\n' \"Traceback (most recent call last):\" >&2\n"
        "printf '%s\\n' \"TypeError: dataclass() got an unexpected keyword argument 'slots'\" >&2\n"
        "exit 1\n",
    )


def _write_good_python(path: Path) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f'exec {sys.executable!s} "$@"\n',
    )


def _write_version_probe_only_python(path: Path, unexpected_log: Path) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == "-c" && "${2:-}" == *"sys.version_info[:3]"* ]]; then\n'
        "  printf '3.12.1\\n'\n"
        "  exit 0\n"
        "fi\n"
        f"printf '%s\\n' \"$*\" >> {unexpected_log!s}\n"
        "printf '%s\\n' 'unexpected python execution before arg parsing' >&2\n"
        "exit 97\n",
    )


def test_install_help_does_not_import_provider_config_before_arg_parse(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    unexpected_log = tmp_path / "unexpected-python.log"
    _write_version_probe_only_python(root.parent / "bin" / "python3.12", unexpected_log)

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **_base_env(),
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Usage: scripts/install.sh" in result.stdout
    assert not unexpected_log.exists(), "provider config should not run before args are parsed"


@pytest.mark.skipif(not Path("/opt/homebrew/bin/python3.12").exists(), reason="requires Homebrew python3.12")
def test_install_auto_selects_supported_python_before_preflight_import(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    bad_log = tmp_path / "bad-python.log"
    _write_bad_python3(root.parent / "bin" / "python3", bad_log)

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--dry-run",
            "--project",
            "pyselect49",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **_base_env(),
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Using Python 3.12" in combined
    assert "/opt/homebrew/bin/python3.12" in combined
    assert "core/preflight.py --project pyselect49 --phase bootstrap" in combined
    assert "dataclass() got an unexpected keyword argument 'slots'" not in combined
    assert not bad_log.exists(), "installer should probe bad python3 but never execute preflight with it"


def test_install_hard_fails_on_explicit_unsupported_python_bin(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    bad_log = tmp_path / "bad-python-explicit.log"
    bad_python = tmp_path / "python3-bad.sh"
    _write_bad_python3(bad_python, bad_log)
    _write_good_python(root.parent / "bin" / "python3.12")

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--dry-run",
            "--project",
            "pyselect50",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **_base_env(),
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": str(bad_python),
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 2
    combined = result.stdout + result.stderr
    assert "requires Python >= 3.11 before preflight can import" in combined
    assert "PYTHON_BIN=" in combined
    assert "python3.12" in combined
    assert "preflight ok" not in combined
    assert not bad_log.exists(), "explicit bad interpreter should be rejected before preflight executes"
