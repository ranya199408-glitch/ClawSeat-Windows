from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_AGENT_ADMIN = _REPO / "core" / "scripts" / "agent_admin.py"
_DISPATCH_TASK = _REPO / "core" / "skills" / "gstack-harness" / "scripts" / "dispatch_task.py"


def _write_local_toml(tmp_path: Path, project: str) -> Path:
    local_toml = tmp_path / f"{project}-local.toml"
    local_toml.write_text(
        "\n".join(
            [
                f'project_name = "{project}"',
                f'repo_root = "{_REPO}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return local_toml


def _run_bootstrap(home: Path, local_toml: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(_AGENT_ADMIN),
            "project",
            "bootstrap",
            "--template",
            "clawseat-solo",
            "--local",
            str(local_toml),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home), "CLAWSEAT_REAL_HOME": str(home)},
        check=False,
    )


def test_project_bootstrap_renders_profile_and_dispatch_can_load_it(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = "ll-render"
    result = _run_bootstrap(home, _write_local_toml(tmp_path, project))

    assert result.returncode == 0, result.stderr
    profile = home / ".agents" / "profiles" / f"{project}-profile-dynamic.toml"
    text = profile.read_text(encoding="utf-8")
    assert f'profile_name = "{project}"' in text
    assert 'seats = ["memory", "builder", "planner"]' in text

    dispatch = subprocess.run(
        [
            sys.executable,
            str(_DISPATCH_TASK),
            "--profile",
            str(profile),
            "--source",
            "planner",
            "--target",
            "builder",
            "--task-id",
            "ll-profile-render-smoke",
            "--title",
            "LL profile render smoke",
            "--objective",
            "Verify bootstrap rendered the dynamic profile.",
            "--test-policy",
            "EXTEND",
            "--reply-to",
            "planner",
            "--no-notify",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home), "CLAWSEAT_REAL_HOME": str(home)},
        check=False,
    )
    assert dispatch.returncode == 0, dispatch.stderr
    assert "FileNotFoundError" not in dispatch.stderr
