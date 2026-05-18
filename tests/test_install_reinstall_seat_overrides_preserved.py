from __future__ import annotations

import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


REPO = Path(__file__).resolve().parents[1]
PROJECT_SH = REPO / "scripts" / "install" / "lib" / "project.sh"


def _run_restore_merge(current: Path, backup: Path) -> subprocess.CompletedProcess[str]:
    command = textwrap.dedent(
        f"""\
        set -euo pipefail
        PYTHON_BIN={shlex.quote(sys.executable)}
        source {shlex.quote(str(PROJECT_SH))}
        DRY_RUN=0
        REINSTALL_PROJECT_TOML_EXISTED=1
        REINSTALL_PROJECT_TOML_BACKUP={shlex.quote(str(backup))}
        PROJECT_RECORD_PATH={shlex.quote(str(current))}
        _restore_reinstall_project_seat_overrides
        """
    )
    return subprocess.run(
        ["bash", "-lc", command],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )


def test_restore_reinstall_project_seat_overrides_merges_backup_blocks(tmp_path: Path) -> None:
    current = tmp_path / "project.toml"
    backup = tmp_path / "project.toml.bak.123"

    current.write_text(
        textwrap.dedent(
            """\
            version = 1
            name = "proj"
            repo_root = "/tmp/proj"
            monitor_session = "project-proj-monitor"

            [seat_overrides.memory]
            tool = "claude"
            auth_mode = "oauth"
            provider = "anthropic"
            model = "gpt-5.4-mini"

            [seat_overrides.builder]
            tool = "codex"
            auth_mode = "oauth"
            provider = "openai"
            """
        ),
        encoding="utf-8",
    )
    backup.write_text(
        textwrap.dedent(
            """\
            version = 1
            name = "proj"
            repo_root = "/tmp/proj"
            monitor_session = "project-proj-monitor"

            [seat_overrides.memory]
            tool = "claude"
            auth_mode = "oauth"
            provider = "anthropic"
            model = "gpt-5-mini"

            [seat_overrides.planner]
            tool = "claude"
            auth_mode = "api"
            provider = "deepseek"
            model = "deepseek-v4-pro[1M]"
            """
        ),
        encoding="utf-8",
    )

    result = _run_restore_merge(current, backup)

    assert result.returncode == 0, result.stderr
    rebuilt = tomllib.loads(current.read_text(encoding="utf-8"))
    assert rebuilt["seat_overrides"]["memory"]["model"] == "gpt-5-mini"
    assert rebuilt["seat_overrides"]["planner"]["provider"] == "deepseek"
    assert rebuilt["seat_overrides"]["builder"]["provider"] == "openai"
