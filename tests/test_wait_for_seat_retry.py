from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "wait-for-seat.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_wait_for_seat_retries_attach_when_session_stays_alive(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    attach_count = tmp_path / "attach-count"

    _write_executable(
        bin_dir / "agentctl.sh",
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${1:-}" == "session-name" ]]; then
              seat="${2:-}"
              project="install"
              while (($#)); do
                case "${1:-}" in
                  --project)
                    project="${2:-$project}"
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
            exit 1
            """
        ),
    )
    _write_executable(
        bin_dir / "tmux",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            state_file={attach_count!s}
            cmd="${{1:-}}"
            shift || true
            case "$cmd" in
              has-session)
                count=0
                if [[ -f "$state_file" ]]; then
                  count="$(cat "$state_file")"
                fi
                if [[ "$count" -lt 2 ]]; then
                  exit 0
                fi
                exit 1
                ;;
              attach)
                count=0
                if [[ -f "$state_file" ]]; then
                  count="$(cat "$state_file")"
                fi
                count=$((count + 1))
                printf '%s' "$count" > "$state_file"
                if [[ "$count" -eq 1 ]]; then
                  exit 0
                fi
                exit 7
                ;;
              capture-pane)
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
        bin_dir / "sleep",
        "#!/usr/bin/env bash\nexit 0\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["AGENTCTL_BIN"] = str(bin_dir / "agentctl.sh")
    env["WAIT_FOR_SEAT_POLL_SECONDS"] = "0"
    env["WAIT_FOR_SEAT_RECONNECT_PAUSE"] = "0"

    result = subprocess.run(
        ["bash", str(SCRIPT), "install", "planner"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 7
    assert attach_count.read_text(encoding="utf-8") == "2"
    assert "DETACHED from install-planner-claude - reconnecting in 0s ..." in result.stdout
