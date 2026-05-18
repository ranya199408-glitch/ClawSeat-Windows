from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core" / "shell-scripts" / "send-and-verify.sh"


def _write_exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _make_env(tmp_path: Path, *, capture_mode: str) -> tuple[dict[str, str], Path]:
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "calls.log"
    count_file = tmp_path / "capture.count"
    base_path = os.environ.get("PATH", "/usr/bin:/bin")

    _write_exe(
        bin_dir / "agentctl.sh",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf 'agentctl %s\\n' "$*" >> '{log_file}'
            shift
            while [ $# -gt 0 ]; do
              case "$1" in
                --project) shift 2 ;;
                *) echo 'resolved-stub-session'; exit 0 ;;
              esac
            done
            echo 'resolved-stub-session'
            """
        ),
    )
    _write_exe(
        bin_dir / "tmux-send",
        f"#!/usr/bin/env bash\nprintf 'tmux-send %s\\n' \"$*\" >> '{log_file}'\nexit 0\n",
    )
    _write_exe(
        bin_dir / "sleep",
        f"#!/usr/bin/env bash\nprintf 'sleep %s\\n' \"$*\" >> '{log_file}'\nexit 0\n",
    )
    _write_exe(
        bin_dir / "tmux",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            printf 'tmux %s\\n' "$*" >> '{log_file}'
            case "$1" in
              has-session)
                exit 0
                ;;
              capture-pane)
                count=0
                if [ -f '{count_file}' ]; then
                  count="$(cat '{count_file}')"
                fi
                count=$((count + 1))
                printf '%s\\n' "$count" > '{count_file}'
                printf 'capture-pane #%s\\n' "$count" >> '{log_file}'
                case '{capture_mode}' in
                  idle)
                    printf 'prompt\\n'
                    ;;
                  busy-then-idle)
                    if [ "$count" -lt 3 ]; then
                      printf 'Working...\\n'
                    else
                      printf 'prompt\\n'
                    fi
                    ;;
                  busy)
                    printf 'Thinking...\\n'
                    ;;
                  *)
                    printf 'prompt\\n'
                    ;;
                esac
                exit 0
                ;;
              send-keys)
                printf 'send-keys %s\\n' "$*" >> '{log_file}'
                exit 0
                ;;
              *)
                exit 0
                ;;
            esac
            """
        ),
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "PATH": f"{bin_dir}{os.pathsep}{base_path}",
            "AGENTCTL_BIN": str(bin_dir / "agentctl.sh"),
            "TMUX_BIN": str(bin_dir / "tmux"),
            "CLAWSEAT_SEND_ALLOW_NO_PROJECT": "1",
        }
    )
    return env, log_file


def _run(script_args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)] + script_args,
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def test_send_waits_for_idle_before_tmux_send(tmp_path: Path) -> None:
    env, log_file = _make_env(tmp_path, capture_mode="idle")
    result = _run(["--project", "demo", "target-seat", "hello"], env=env)
    assert result.returncode == 0, result.stderr
    assert "SENT: resolved-stub-session" in result.stdout
    calls = log_file.read_text(encoding="utf-8").splitlines()
    assert "capture-pane #1" in calls
    assert any(line.startswith("tmux-send ") for line in calls)
    assert calls.index("capture-pane #1") < next(i for i, line in enumerate(calls) if line.startswith("tmux-send "))


def test_send_waits_through_busy_then_idles(tmp_path: Path) -> None:
    env, log_file = _make_env(tmp_path, capture_mode="busy-then-idle")
    result = _run(["--project", "demo", "target-seat", "hello"], env=env)
    assert result.returncode == 0, result.stderr
    assert "SENT: resolved-stub-session" in result.stdout
    calls = log_file.read_text(encoding="utf-8").splitlines()
    capture_calls = [line for line in calls if line.startswith("capture-pane #")]
    assert capture_calls == ["capture-pane #1", "capture-pane #2", "capture-pane #3"]
    sleep_calls = [line for line in calls if line.startswith("sleep ")]
    assert sleep_calls == ["sleep 4", "sleep 4"]
    assert any(line.startswith("tmux-send ") for line in calls)


def test_send_times_out_fails_closed_without_force(tmp_path: Path) -> None:
    env, log_file = _make_env(tmp_path, capture_mode="busy")
    result = _run(["--project", "demo", "target-seat", "hello"], env=env)
    assert result.returncode == 1, result.stderr
    assert "send-and-verify: FAIL_CLOSED target busy after 120s; use --force to override" in result.stderr
    calls = log_file.read_text(encoding="utf-8").splitlines()
    capture_calls = [line for line in calls if line.startswith("capture-pane #")]
    sleep_calls = [line for line in calls if line.startswith("sleep ")]
    assert len(capture_calls) == 30
    assert len(sleep_calls) == 30
    assert not any(line.startswith("tmux-send ") for line in calls)
    assert not any(line.startswith("send-keys ") for line in calls)


def test_send_times_out_with_force_overrides_fail_closed(tmp_path: Path) -> None:
    env, log_file = _make_env(tmp_path, capture_mode="busy")
    result = _run(["--project", "demo", "--force", "target-seat", "hello"], env=env)
    assert result.returncode == 0, result.stderr
    assert "send-and-verify: WARN target busy after 120s, sending anyway (--force)" in result.stderr
    calls = log_file.read_text(encoding="utf-8").splitlines()
    capture_calls = [line for line in calls if line.startswith("capture-pane #")]
    sleep_calls = [line for line in calls if line.startswith("sleep ")]
    assert len(capture_calls) == 30
    assert len(sleep_calls) == 30
    assert any(line.startswith("tmux-send ") for line in calls)
