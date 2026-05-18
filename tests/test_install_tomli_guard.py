from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


_HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_install_isolation_helpers_tomli", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_fake_install_root = _HELPERS._fake_install_root


def test_install_self_heals_missing_tomli_before_env_scan(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = _fake_install_root(tmp_path)
    pip_log = tmp_path / "pip.log"
    wrapper = tmp_path / "python-wrapper.sh"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == "-c" && "${2:-}" == "import tomllib" ]]; then exit 1; fi\n'
        'if [[ "${1:-}" == "-c" && "${2:-}" == "import tomli" ]]; then exit 1; fi\n'
        'if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then\n'
        '  printf "%s\\n" "$*" >> "${PIP_LOG:?}"\n'
        "  exit 0\n"
        "fi\n"
        'exec "${REAL_PYTHON:?}" "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = subprocess.run(
        [
            "bash",
            str(root / "scripts" / "install.sh"),
            "--dry-run",
            "--project",
            "tomli50",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "HOME": str(home),
            "CLAWSEAT_REAL_HOME": str(home),
            "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
            "PYTHON_BIN": str(wrapper),
            "REAL_PYTHON": sys.executable,
            "PIP_LOG": str(pip_log),
            "LOG_FILE": str(launcher_log),
            "TMUX_LOG_FILE": str(tmux_log),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Step 2.5: ensure Python tomllib fallback" in result.stdout
    assert pip_log.read_text(encoding="utf-8").strip().endswith("pip install --user --quiet tomli")
