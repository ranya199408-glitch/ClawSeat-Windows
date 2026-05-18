from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "apply-koder-overlay.sh"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _seed_home(tmp_path: Path) -> Path:
    real_home = tmp_path / "home"
    for name in ("a", "b", "c"):
        (real_home / ".openclaw" / f"workspace-{name}").mkdir(parents=True, exist_ok=True)
    (real_home / ".agents" / "profiles").mkdir(parents=True, exist_ok=True)
    (real_home / ".agents" / "profiles" / "install-profile-dynamic.toml").write_text(
        'profile_name = "install"\n',
        encoding="utf-8",
    )
    return real_home


def _run(
    args: list[str],
    *,
    real_home: Path,
    input_text: str = "",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "CLAWSEAT_REAL_HOME": str(real_home),
            "HOME": str(real_home),
            "PYTHON_BIN": sys.executable,
        }
    )
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=input_text,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
    )


def test_dry_run_lists_menu_items(tmp_path: Path) -> None:
    real_home = _seed_home(tmp_path)

    result = _run(["--dry-run", "install"], real_home=real_home)

    assert result.returncode == 0, result.stderr
    assert "可选的 OpenClaw agent" in result.stdout
    assert "[1] a" in result.stdout
    assert "[2] b" in result.stdout
    assert "[3] c" in result.stdout


def test_pick_first_invokes_init_and_bind(tmp_path: Path) -> None:
    real_home = _seed_home(tmp_path)
    log_path = tmp_path / "calls.log"
    runner = _write(
        tmp_path / "runner.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$0 $*\" >> \"$CALLS_LOG\"\n",
    )

    result = _run(
        ["install"],
        real_home=real_home,
        input_text="1\ny\n",
        extra_env={
            "CALLS_LOG": str(log_path),
            "INIT_KODER_RUNNER": str(runner),
            "KODER_BIND_RUNNER": str(runner),
        },
    )

    assert result.returncode == 0, result.stderr
    log = log_path.read_text(encoding="utf-8")
    assert "--workspace" in log
    assert str(real_home / ".openclaw" / "workspace-a") in log
    assert "--tenant a" in log
    assert "OK: 'a' 已改造为 koder" in result.stdout


def test_dry_run_does_not_execute_runners(tmp_path: Path) -> None:
    real_home = _seed_home(tmp_path)
    marker = tmp_path / "executed.txt"
    runner = _write(
        tmp_path / "runner-touch.sh",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "touch \"$MARKER\"\n",
    )

    result = _run(
        ["--dry-run", "install", "<FEISHU_GROUP_ID>"],
        real_home=real_home,
        extra_env={
            "MARKER": str(marker),
            "INIT_KODER_RUNNER": str(runner),
            "KODER_BIND_RUNNER": str(runner),
            "CONFIGURE_KODER_FEISHU_RUNNER": str(runner),
            "OPENCLAW_HOME": str(real_home / ".openclaw"),
        },
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "[dry-run]" in result.stdout
    assert "configure_koder_feishu" in result.stdout or "runner-touch.sh" in result.stdout


def test_destructive_banner_visible_at_runtime(tmp_path: Path) -> None:
    """Runtime banner must include DESTRUCTIVE and B2.5 before 'Step 1'."""
    real_home = _seed_home(tmp_path)
    # --dry-run so we don't need full OpenClaw setup
    result = _run(["--dry-run", "install"], real_home=real_home)
    out = result.stdout
    assert "DESTRUCTIVE" in out, f"banner must say DESTRUCTIVE; stdout:\n{out}"
    assert "B2.5" in out, f"banner must mention B2.5; stdout:\n{out}"
    # Banner must appear before Step 1 output
    if "Step 1" in out:
        assert out.index("DESTRUCTIVE") < out.index("Step 1"), (
            "DESTRUCTIVE banner must appear before 'Step 1'"
        )


def test_destructive_banner_suppressed_by_quiet(tmp_path: Path) -> None:
    """--quiet flag must suppress the banner entirely."""
    real_home = _seed_home(tmp_path)
    result = _run(["--quiet", "--dry-run", "install"], real_home=real_home)
    assert "DESTRUCTIVE" not in result.stdout, (
        f"--quiet should suppress DESTRUCTIVE banner; stdout:\n{result.stdout}"
    )


def test_koder_bind_runner_threads_group_id(tmp_path: Path) -> None:
    """KODER_BIND_RUNNER must receive --feishu-group-id when FEISHU_GROUP_ID is set.

    Uses positional arg for group_id (the script's documented CLI surface) and
    full input sequence (pick=1 + confirm=y) so the script reaches run_koder_bind.
    """
    real_home = _seed_home(tmp_path)
    args_log = tmp_path / "runner-args.txt"
    runner = _write(
        tmp_path / "bind-runner.sh",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" >> '{args_log}'\nexit 0\n",
    )
    init_runner = _write(
        tmp_path / "init-noop.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )

    result = _run(
        ["install", "<FEISHU_GROUP_ID>"],   # group_id as positional arg
        real_home=real_home,
        input_text="1\ny\n",                          # pick=1 + confirm=y
        extra_env={
            "INIT_KODER_RUNNER": str(init_runner),
            "KODER_BIND_RUNNER": str(runner),
            "CONFIGURE_KODER_FEISHU_RUNNER": "true",  # no-op feishu config (any non-empty)
        },
    )

    # Hard assertions — no `if args_log.exists()` guard.
    assert result.returncode == 0, f"script failed: rc={result.returncode}\nstderr:\n{result.stderr}"
    assert args_log.exists(), (
        f"KODER_BIND_RUNNER stub was never invoked.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    args_text = args_log.read_text(encoding="utf-8")
    assert "--feishu-group-id" in args_text, (
        f"KODER_BIND_RUNNER must receive --feishu-group-id; args logged:\n{args_text}"
    )
    assert "<FEISHU_GROUP_ID>" in args_text, (
        f"--feishu-group-id value not present in runner args:\n{args_text}"
    )


def test_koder_bind_runner_no_flag_when_empty_group_id(tmp_path: Path) -> None:
    """When no group_id positional arg is supplied, --feishu-group-id must NOT be passed."""
    real_home = _seed_home(tmp_path)
    args_log = tmp_path / "runner-args-empty.txt"
    runner = _write(
        tmp_path / "bind-runner-empty.sh",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" >> '{args_log}'\nexit 0\n",
    )
    init_runner = _write(
        tmp_path / "init-noop-empty.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )

    result = _run(
        ["install"],                                  # no positional group_id
        real_home=real_home,
        input_text="1\ny\n",
        extra_env={
            "INIT_KODER_RUNNER": str(init_runner),
            "KODER_BIND_RUNNER": str(runner),
            "CONFIGURE_KODER_FEISHU_RUNNER": "true",
        },
    )

    assert result.returncode == 0, f"script failed: rc={result.returncode}\nstderr:\n{result.stderr}"
    assert args_log.exists(), "KODER_BIND_RUNNER stub was never invoked"

    args_text = args_log.read_text(encoding="utf-8")
    assert "--feishu-group-id" not in args_text, (
        f"Empty group_id must NOT produce --feishu-group-id flag; args:\n{args_text}"
    )
