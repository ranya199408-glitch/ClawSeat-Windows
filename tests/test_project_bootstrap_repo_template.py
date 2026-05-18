from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_AGENT_ADMIN = _REPO / "core" / "scripts" / "agent_admin.py"


def test_project_bootstrap_supports_repo_root_single_file_template(tmp_path: Path) -> None:
    home = tmp_path / "home"
    local_toml = tmp_path / "local.toml"
    local_toml.write_text(
        "\n".join(
            [
                'project_name = "spawn49"',
                f'repo_root = "{_REPO}"',
                "",
                "[[overrides]]",
                'id = "memory"',
                'session_name = "spawn49-memory"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(_AGENT_ADMIN),
            "project",
            "bootstrap",
            "--template",
            "clawseat-creative",
            "--local",
            str(local_toml),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "CLAWSEAT_REAL_HOME": str(home),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "bootstrapped spawn49" in result.stdout
    assert "warning\tapi secrets not provisioned" in result.stdout

    agents_root = home / ".agents"
    project_toml = agents_root / "projects" / "spawn49" / "project.toml"
    assert project_toml.is_file()
    assert 'template_name = "clawseat-creative"' in project_toml.read_text(encoding="utf-8")

    session_tomls = sorted((agents_root / "sessions" / "spawn49").glob("*/session.toml"))
    engineer_tomls = sorted((agents_root / "engineers").glob("*/engineer.toml"))

    assert len(session_tomls) == 5
    assert len(engineer_tomls) == 5
    assert {
        path.parent.name for path in session_tomls
    } == {"memory", "writer", "builder-image", "builder-av", "patrol"}
