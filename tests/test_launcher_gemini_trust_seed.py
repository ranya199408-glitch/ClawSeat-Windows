from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_LAUNCHER = _REPO / "core" / "launchers" / "agent-launcher.sh"


def _run_bash(real_home: Path, snippet: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(real_home),
        "CLAWSEAT_AGENT_LAUNCHER_LIBRARY_ONLY": "1",
    }
    for key in ("AGENTS_ROOT", "CLAWSEAT_PROJECT", "CLAWSEAT_SEAT", "CLAWSEAT_ENGINEER_ID"):
        env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            "bash",
            "-c",
            "\n".join(
                [
                    "set -euo pipefail",
                    f"source {shlex.quote(str(_LAUNCHER))}",
                    snippet,
                ]
            ),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_prepare_gemini_home_writes_trusted_folders_and_preserves_existing_entries(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime_home"
    real_home.mkdir(parents=True)
    runtime_home.mkdir(parents=True)

    gemini_home = real_home / ".gemini"
    gemini_home.mkdir(parents=True, exist_ok=True)
    (gemini_home / "trustedFolders.json").write_text(
        json.dumps({"/tmp/fake-home": "TRUST_FOLDER"}, indent=2),
        encoding="utf-8",
    )

    result = _run_bash(
        real_home,
        f"prepare_gemini_home {shlex.quote(str(runtime_home))} /tmp/test-workdir",
    )

    assert result.returncode == 0, result.stderr
    trust_file = runtime_home / ".gemini" / "trustedFolders.json"
    data = json.loads(trust_file.read_text(encoding="utf-8"))
    assert data["/tmp/fake-home"] == "TRUST_FOLDER"
    assert data["/tmp/test-workdir"] == "TRUST_FOLDER"
    assert json.loads((gemini_home / "trustedFolders.json").read_text(encoding="utf-8")) == {
        "/tmp/fake-home": "TRUST_FOLDER",
    }


def test_run_gemini_runtime_oauth_branch_seeds_trusted_folder(tmp_path: Path) -> None:
    real_home = tmp_path / "real_home"
    workdir = tmp_path / "test-workdir"
    real_home.mkdir(parents=True)
    workdir.mkdir(parents=True, exist_ok=True)
    gemini_home = real_home / ".gemini"
    gemini_home.mkdir(parents=True, exist_ok=True)
    (gemini_home / "trustedFolders.json").write_text(
        json.dumps({"/tmp/fake-home": "TRUST_FOLDER"}, indent=2),
        encoding="utf-8",
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "gemini.log"
    (bin_dir / "gemini").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$(cat \"$HOME/.gemini/trustedFolders.json\")\" > \"${GEMINI_LOG_FILE:?}\"\n",
        encoding="utf-8",
    )
    (bin_dir / "gemini").chmod(0o755)

    result = _run_bash(
        real_home,
        f"run_gemini_runtime oauth {shlex.quote(str(workdir))} gemini-session",
        extra_env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GEMINI_LOG_FILE": str(log_file),
        },
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(log_file.read_text(encoding="utf-8"))
    assert data["/tmp/fake-home"] == "TRUST_FOLDER"
    assert data[str(workdir)] == "TRUST_FOLDER"
