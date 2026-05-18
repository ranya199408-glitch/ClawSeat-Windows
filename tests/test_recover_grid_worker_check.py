from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "recover-grid.sh"
REAL_PYTHON = sys.executable


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _write_project_toml(home: Path, project: str) -> None:
    project_dir = home / ".agents" / "projects" / project
    project_dir.mkdir(parents=True, exist_ok=True)
    project_dir.joinpath("project.toml").write_text(
        textwrap.dedent(
            """\
            version = 1
            name = "proj"
            repo_root = "/tmp/proj"
            monitor_session = "project-proj-monitor"
            template_name = "clawseat-minimal"
            window_mode = "split-2"
            monitor_max_panes = 4
            open_detail_windows = false
            engineers = ["memory", "planner", "builder"]
            monitor_engineers = ["memory", "planner", "builder"]
            """
        ),
        encoding="utf-8",
    )


def test_recover_grid_warns_when_worker_clients_drop_to_zero(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_project_toml(home, "proj")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _write_executable(
        bin_dir / "python3",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            real_python={REAL_PYTHON!s}
            if [[ "${{1:-}}" == *"/core/scripts/agent_admin.py" && "${{2:-}}" == "session-name" ]]; then
              project="proj"
              seat="${{3:-}}"
              shift 3
              while (($#)); do
                case "${{1:-}}" in
                  --project)
                    project="${{2:-$project}}"
                    shift 2
                    ;;
                  *)
                    shift
                    ;;
                esac
              done
              printf '%s-%s-claude\\n' "$project" "$seat"
              exit 0
            fi
            exec "$real_python" "$@"
            """
        ),
    )
    _write_executable(
        bin_dir / "tmux",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            cmd="${1:-}"
            shift || true
            case "$cmd" in
              has-session)
                exit 0
                ;;
              list-clients)
                case "$*" in
                  *proj-memory-claude*)
                    printf '/dev/ttys001\\n'
                    ;;
                esac
                exit 0
                ;;
              detach-client)
                exit 0
                ;;
              *)
                echo "unexpected tmux command: $cmd" >&2
                exit 2
                ;;
            esac
            """
        ),
    )
    _write_executable(
        bin_dir / "osascript",
        "#!/usr/bin/env bash\nprintf '1\\n'\n",
    )
    _write_executable(
        bin_dir / "ls",
        "#!/usr/bin/env bash\nexit 0\n",
    )
    _write_executable(
        bin_dir / "sysctl",
        "#!/usr/bin/env bash\nprintf '10\\n'\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["HOME"] = str(home)
    env["CLAWSEAT_REAL_HOME"] = str(home)

    result = subprocess.run(
        ["bash", str(SCRIPT), "proj"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert "ok: proj-memory-claude has 1 client(s) — no recovery needed" in result.stdout
    assert "warn: worker seat 'planner' has 0 tmux client(s) on 'proj-planner-claude'" in result.stderr
    assert "warn: worker seat 'builder' has 0 tmux client(s) on 'proj-builder-claude'" in result.stderr
    assert "agent_admin tmux clean-stale-clients" not in result.stderr
