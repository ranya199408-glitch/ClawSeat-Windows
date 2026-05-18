from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "core" / "scripts" / "seat-diagnostic.sh"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_session(home: Path, *, project: str = "demo", seat: str = "builder") -> None:
    session_dir = home / ".agents" / "sessions" / project / seat
    session_dir.mkdir(parents=True)
    runtime = home / ".agents" / "runtime" / "identities" / "codex" / "api" / "codex.api.xcode.demo.builder"
    (runtime / "codex-home" / "log").mkdir(parents=True)
    (runtime / "codex-home" / "log" / "codex-tui.log").write_text("real error line\n", encoding="utf-8")
    secret = home / ".agents" / "secrets" / "codex" / "xcode-best" / f"{seat}.env"
    secret.parent.mkdir(parents=True)
    secret.write_text(
        "OPENAI_API_KEY=<OPENAI_API_KEY>\nOPENAI_BASE_URL=https://unit.test/v1\n",
        encoding="utf-8",
    )
    (session_dir / "session.toml").write_text(
        f"""\
version = 1
project = "{project}"
engineer_id = "{seat}"
tool = "codex"
auth_mode = "api"
provider = "xcode-best"
identity = "codex.api.xcode.demo.builder"
workspace = "{home / ".agents" / "workspaces" / project / seat}"
runtime_dir = "{runtime}"
session = "{project}-{seat}-codex"
bin_path = "/usr/bin/codex"
secret_file = "{secret}"
""",
        encoding="utf-8",
    )


def _write_project(home: Path, *, project: str = "demo", seat: str = "builder") -> None:
    project_dir = home / ".agents" / "projects" / project
    project_dir.mkdir(parents=True)
    (project_dir / "project.toml").write_text(
        f"""\
version = 1
name = "{project}"
engineers = ["memory", "{seat}"]

[seat_overrides.{seat}]
tool = "codex"
auth_mode = "api"
provider = "xcode-best"
""",
        encoding="utf-8",
    )


def _write_stubs(bin_dir: Path, *, curl_code: str = "200") -> tuple[Path, Path]:
    bin_dir.mkdir(parents=True)
    agentctl_log = bin_dir / "agentctl.log"
    curl_log = bin_dir / "curl.log"
    _write_executable(
        bin_dir / "agentctl",
        f"""\
#!/bin/sh
echo "$@" >> {agentctl_log}
echo demo-builder-codex
""",
    )
    _write_executable(
        bin_dir / "tmux",
        """\
#!/bin/sh
case "$1" in
  has-session) exit 0 ;;
  list-clients) echo "client-1"; exit 0 ;;
  capture-pane) echo "pane tail"; exit 0 ;;
  *) exit 1 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "curl",
        f"""\
#!/bin/sh
echo "$@" >> {curl_log}
printf '{curl_code}'
""",
    )
    return agentctl_log, curl_log


def _run(home: Path, bin_dir: Path, *, project: str = "demo", seat: str = "builder") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["AGENT_HOME"] = str(home)
    env["HOME"] = str(home)
    env["AGENTS_ROOT"] = str(home / ".agents")
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(
        ["bash", str(_SCRIPT), project, seat],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_diagnostic_resolves_session_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    _write_project(home)
    agentctl_log, _curl_log = _write_stubs(bin_dir)

    result = _run(home, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "session = demo-builder-codex" in result.stdout
    assert "session-name builder --project demo" in agentctl_log.read_text(encoding="utf-8")


def test_diagnostic_includes_all_four_blocks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    _write_project(home)
    _write_session(home)
    _write_stubs(bin_dir)

    result = _run(home, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "=== TMUX ===" in result.stdout
    assert "=== LOG (tail 30) ===" in result.stdout
    assert "=== ENDPOINT ===" in result.stdout
    assert "=== SECRETS ===" in result.stdout
    assert "log: real error line" in result.stdout


def test_diagnostic_handles_missing_log_file_gracefully(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    _write_project(home)
    _write_session(home)
    runtime_log = next(home.glob(".agents/runtime/identities/codex/api/*/codex-home/log/codex-tui.log"))
    runtime_log.unlink()
    _write_stubs(bin_dir)

    result = _run(home, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "<no log file at" in result.stdout
    assert "=== ENDPOINT ===" in result.stdout


def test_diagnostic_curls_provider_endpoint(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    _write_project(home)
    _write_session(home)
    _agentctl_log, curl_log = _write_stubs(bin_dir, curl_code="204")

    result = _run(home, bin_dir)

    assert result.returncode == 0, result.stderr
    assert "http_code = 204" in result.stdout
    curl_text = curl_log.read_text(encoding="utf-8")
    assert "https://unit.test/v1/models" in curl_text
    assert "Authorization: Bearer test-key" in curl_text
