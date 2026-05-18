from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
_HELPERS_PATH = Path(__file__).with_name("test_launcher_gemini_trust_seed.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_launcher_gemini_trust_seed_helpers_template_copy", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_run_bash = _HELPERS._run_bash

import sys

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from seat_claude_template import ensure_seat_claude_template


def _seed_real_home(real_home: Path) -> None:
    claude_home = real_home / ".claude"
    claude_home.mkdir(parents=True, exist_ok=True)
    (real_home / ".claude.json").write_text('{"hasCompletedOnboarding":true}\n', encoding="utf-8")
    (claude_home / "settings.json").write_text('{"theme":"dark"}\n', encoding="utf-8")
    (claude_home / "statsig").write_text("statsig", encoding="utf-8")
    (claude_home / "commands").mkdir(parents=True, exist_ok=True)
    (claude_home / "agents").mkdir(parents=True, exist_ok=True)
    user_skills = claude_home / "skills"
    user_skills.mkdir(parents=True, exist_ok=True)
    (user_skills / "user-daily-skill").mkdir(parents=True, exist_ok=True)


def _prepare_runtime(tmp_path: Path, seat_id: str) -> tuple[Path, Path]:
    real_home = tmp_path / "real_home"
    runtime_home = tmp_path / "runtime_home"
    real_home.mkdir(parents=True, exist_ok=True)
    runtime_home.mkdir(parents=True, exist_ok=True)
    _seed_real_home(real_home)
    ensure_seat_claude_template(real_home / ".agents" / "engineers", seat_id)

    result = _run_bash(
        real_home,
        f"prepare_claude_home {runtime_home!s}",
        extra_env={
            "AGENTS_ROOT": str(real_home / ".agents"),
            "CLAWSEAT_SEAT": seat_id,
        },
    )
    assert result.returncode == 0, result.stderr
    return real_home, runtime_home


def test_sandbox_claude_skills_are_real_dirs_not_symlinks(tmp_path: Path) -> None:
    _real_home, runtime_home = _prepare_runtime(tmp_path, "planner")

    skills_dir = runtime_home / ".claude" / "skills"
    settings_path = runtime_home / ".claude" / "settings.json"
    assert skills_dir.is_dir()
    assert not skills_dir.is_symlink()
    assert settings_path.is_file()
    assert not settings_path.is_symlink()
    assert all(not child.is_symlink() for child in skills_dir.iterdir())


def test_sandbox_has_only_role_plus_shared_skills(tmp_path: Path) -> None:
    _real_home, runtime_home = _prepare_runtime(tmp_path, "reviewer")

    assert {path.name for path in (runtime_home / ".claude" / "skills").iterdir()} == {
        "reviewer",
        "clawseat",
        "gstack-harness",
        "tmux-basics",
    }


def test_memory_seat_has_stop_hook_in_sandbox(tmp_path: Path) -> None:
    _real_home, runtime_home = _prepare_runtime(tmp_path, "memory")

    settings = json.loads((runtime_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    stop_entries = settings["hooks"]["Stop"]
    assert len(stop_entries) == 1
    assert stop_entries[0]["hooks"][0]["command"].endswith("/scripts/hooks/memory-stop-hook.sh")


def test_non_memory_seats_lack_stop_hook_in_sandbox(tmp_path: Path) -> None:
    _real_home, runtime_home = _prepare_runtime(tmp_path, "patrol")

    settings = json.loads((runtime_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"] == {}
    assert settings["permissions"] == {}


def test_planner_seat_has_planner_skill(tmp_path: Path) -> None:
    _real_home, runtime_home = _prepare_runtime(tmp_path, "planner")

    assert {path.name for path in (runtime_home / ".claude" / "skills").iterdir()} == {
        "planner",
        "clawseat",
        "gstack-harness",
        "tmux-basics",
    }
