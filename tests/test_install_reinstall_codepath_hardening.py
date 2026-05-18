from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


HELPERS_PATH = Path(__file__).with_name("test_install_isolation.py")
HELPERS_SPEC = importlib.util.spec_from_file_location(
    "test_install_isolation_helpers_reinstall", HELPERS_PATH
)
assert HELPERS_SPEC is not None and HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(HELPERS_SPEC)
HELPERS_SPEC.loader.exec_module(_HELPERS)

fake_install_root = _HELPERS._fake_install_root

_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"


def _run_install(
    root: Path,
    home: Path,
    py_stubs: Path,
    *,
    args: list[str],
    input_data: str = "",
    extra_env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "HOME": str(home),
        "CLAWSEAT_REAL_HOME": str(home),
        "PATH": f"{root.parent / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": f"{py_stubs}{os.pathsep}{os.environ.get('PYTHONPATH', '')}",
        "PYTHON_BIN": sys.executable,
        "LOG_FILE": str(root.parent / "launcher.jsonl"),
        "TMUX_LOG_FILE": str(root.parent / "tmux.log"),
        "CLAWSEAT_QA_PATROL_CRON_OPT_IN": "n",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(root / "scripts" / "install.sh"), *args],
        input=input_data,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )


def test_reinstall_memory_tool_override_prevents_provider_override_and_uses_memory_model(tmp_path: Path) -> None:
    root, home, launcher_log, tmux_log, py_stubs = fake_install_root(tmp_path)
    project_dir = home / ".agents" / "projects" / "by-reinstall"
    project_dir.mkdir(parents=True)
    project_toml = project_dir / "project.toml"
    project_toml.write_text(
        "\n".join(
            [
                'name = "by-reinstall"',
                'template_name = "clawseat-creative"',
                "[seat_overrides.memory]",
                'tool = "codex"',
                'model = "gpt-5-mini"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_install(
        root,
        home,
        py_stubs,
        args=[
            "--reinstall",
            "by-reinstall",
            "--template",
            "clawseat-creative",
            "--provider",
            "oauth",
            "--dry-run",
        ],
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "memory-tool=codex" in combined
    assert "auth=chatgpt" in combined
    assert "model=gpt-5-mini" in combined
    assert "skip Claude provider selection" in combined


def _write_project_bootstraping_agent_admin(root: Path) -> None:
    # This agent_admin intentionally skips project bootstrap when profile already exists,
    # allowing BY-2 test to verify stale profile cleanup/rebuild behavior.
    path = root / "core" / "scripts" / "agent_admin.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

log_file = os.environ.get("AGENT_ADMIN_LOG")
if log_file:
    with open(log_file, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")

if sys.argv[1:3] == ["project", "bootstrap"]:
    template = "clawseat-creative"
    local_path = ""
    for idx, arg in enumerate(sys.argv):
        if arg == "--template" and idx + 1 < len(sys.argv):
            template = sys.argv[idx + 1]
        if arg == "--local" and idx + 1 < len(sys.argv):
            local_path = sys.argv[idx + 1]

    project = "smoketest"
    repo_root = os.getcwd()
    if local_path:
        data = tomllib.loads(Path(local_path).read_text(encoding="utf-8"))
        project = str(data.get("project_name") or project)
        repo_root = str(data.get("repo_root") or repo_root)

    seats = ["memory", "planner", "builder", "patrol", "designer"]
    if template == "clawseat-engineering":
        seats.insert(2, "reviewer")

    template_path = Path(__file__).resolve().parents[3] / "templates" / f"{template}.toml"
    if template_path.is_file():
        template_data = tomllib.loads(template_path.read_text(encoding="utf-8"))
        seats = [str(item.get("id", "")) for item in template_data.get("engineers", []) if str(item.get("id", ""))]

    seats_text = ", ".join(f'\"{seat}\"' for seat in seats if seat)
    home = Path(os.environ.get("CLAWSEAT_REAL_HOME") or os.environ["HOME"])
    profile = home / ".agents" / "profiles" / f"{project}-profile-dynamic.toml"
    if profile.exists():
        raise SystemExit(0)

    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(
        "\\n".join(
            [
                "version = 1",
                f'profile_name = "{project}"',
                f'project_name = "{project}"',
                f'repo_root = "{repo_root}"',
                f'seats = [{seats_text}]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    raise SystemExit(0)

raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o111)


def test_reinstall_template_change_regenerates_stale_profile(tmp_path: Path) -> None:
    root, home, _launcher_log, _tmux_log, py_stubs = fake_install_root(tmp_path)
    _write_project_bootstraping_agent_admin(root)

    project_dir = home / ".agents" / "projects" / "by-template-switch"
    project_dir.mkdir(parents=True)
    project_path = project_dir / "project.toml"
    profile_path = home / ".agents" / "profiles" / "by-template-switch-profile-dynamic.toml"
    profile_path.parent.mkdir(parents=True)
    project_path.write_text(
        "\n".join(
            [
                'name = "by-template-switch"',
                'template_name = "clawseat-creative"',
                'engineers = ["memory", "planner", "builder", "patrol", "designer"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    profile_path.write_text(
        "\n".join(
            [
                "version = 1",
                'project_name = "by-template-switch"',
                "seats = [\"memory\", \"planner\", \"builder\", \"patrol\", \"designer\"]",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_install(
        root,
        home,
        py_stubs,
        args=[
            "--reinstall",
            "--project",
            "by-template-switch",
            "--template",
            "clawseat-engineering",
            "--provider",
            "minimax",
        ],
    )
    assert result.returncode == 0, result.stderr

    rebuilt = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    assert "reviewer" in rebuilt["seats"]
    assert "reviewer" in "".join(profile_path.read_text(encoding="utf-8"))
