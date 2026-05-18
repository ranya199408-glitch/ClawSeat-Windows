from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def _read(relpath: str) -> str:
    return (_REPO / relpath).read_text(encoding="utf-8")


def _install_code() -> str:
    parts = [_read("scripts/install.sh")]
    lib_dir = _REPO / "scripts" / "install" / "lib"
    parts.extend(path.read_text(encoding="utf-8") for path in sorted(lib_dir.glob("*.sh")))
    return "\n".join(parts)


def test_install_primary_seat_default_is_memory() -> None:
    text = _install_code()
    assert 'PRIMARY_SEAT_ID="memory"' in text
    assert 'PRIMARY_SEAT_ID="ancestor"' not in text


def test_install_uses_memory_bootstrap_paths() -> None:
    text = _install_code()
    assert "memory-bootstrap.template.md" in text
    assert "memory-bootstrap.md" in text
    assert "memory-kickoff.txt" in text
    assert "memory-provider.env" in text
    assert "ancestor-brief.template.md" not in text
    assert "ancestor-bootstrap.md" not in text
    assert "ancestor-kickoff.txt" not in text
    assert "ancestor-provider.env" not in text


def test_deleted_legacy_files_are_absent() -> None:
    assert not (_REPO / "core" / "templates" / "ancestor-engineer.toml").exists()
    assert not (_REPO / "scripts" / "launch_ancestor.sh").exists()
    assert not (_REPO / "templates" / "clawseat-monitor.yaml").exists()


def test_agent_admin_session_exports_memory_brief_with_legacy_alias() -> None:
    text = _read("core/scripts/agent_admin_session.py")
    assert "def _memory_brief_path" in text
    assert "memory-bootstrap.md" in text
    assert "CLAWSEAT_MEMORY_BRIEF" in text
    assert "CLAWSEAT_ANCESTOR_BRIEF" in text
    assert "def _ancestor_brief_path" not in text


def test_memory_brief_drift_check_accepts_new_env_name() -> None:
    text = _read("scripts/memory-brief-mtime-check.sh")
    assert "CLAWSEAT_MEMORY_BRIEF" in text
    assert "memory_started_unix" in text
    assert "ancestor_started_unix" not in text


def test_qa_patrol_template_targets_memory_session() -> None:
    text = _read("core/templates/patrol.plist.in")
    assert "com.clawseat.{PROJECT}.patrol" in text
    assert "session-name memory --project" in text
    assert "--project '{PROJECT}' memory" in text
    assert "ancestor-patrol" not in text


def test_profile_defaults_route_to_memory() -> None:
    profile_template = _read("core/templates/profile-dynamic.template.toml")
    migrate_profile = _read("core/skills/gstack-harness/scripts/migrate_profile.py")
    common = _read("core/skills/gstack-harness/scripts/_common.py")

    assert 'active_loop_owner = "memory"' in profile_template
    assert 'default_notify_target = "memory"' in profile_template
    assert 'data.get("active_loop_owner", "memory")' in migrate_profile
    assert 'data.get("default_notify_target", "memory")' in migrate_profile
    assert 'data.get("active_loop_owner", "memory")' in common
    assert 'data.get("default_notify_target", "memory")' in common


def test_migrate_ancestor_paths_renames_and_symlinks(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = "demo"
    tasks = home / ".agents" / "tasks" / project
    handoffs = tasks / "patrol" / "handoffs"
    handoffs.mkdir(parents=True)
    (handoffs / "ancestor-bootstrap.md").write_text("brief\n", encoding="utf-8")
    (handoffs / "ancestor-kickoff.txt").write_text("kickoff\n", encoding="utf-8")
    (tasks / "ancestor-provider.env").write_text("PROVIDER=minimax\n", encoding="utf-8")
    profiles = home / ".agents" / "profiles"
    profiles.mkdir(parents=True)
    profile = profiles / f"{project}-profile-dynamic.toml"
    profile.write_text(
        'active_loop_owner = "planner"\ndefault_notify_target = "planner"\n',
        encoding="utf-8",
    )

    env = {**os.environ, "HOME": str(home), "CLAWSEAT_REAL_HOME": str(home)}
    cmd = [sys.executable, str(_REPO / "core" / "scripts" / "migrate_ancestor_paths.py"), "--project", project]
    first = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)
    second = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (handoffs / "memory-bootstrap.md").read_text(encoding="utf-8") == "brief\n"
    assert (handoffs / "memory-kickoff.txt").read_text(encoding="utf-8") == "kickoff\n"
    assert (tasks / "memory-provider.env").read_text(encoding="utf-8") == "PROVIDER=minimax\n"
    assert (handoffs / "ancestor-bootstrap.md").is_symlink()
    assert (handoffs / "ancestor-kickoff.txt").is_symlink()
    assert (tasks / "ancestor-provider.env").is_symlink()
    assert 'active_loop_owner = "memory"' in profile.read_text(encoding="utf-8")
    assert 'default_notify_target = "memory"' in profile.read_text(encoding="utf-8")


def test_requiremention_cookbook_is_in_memory_and_koder_skills() -> None:
    memory = _read("core/skills/memory-oracle/SKILL.md")
    koder = _read("core/skills/clawseat-koder/SKILL.md")

    assert "Feishu requireMention 双层配置" in memory
    assert "requireMention: true" in memory
    assert "需要@机器人才能回复" in memory
    assert "Feishu requireMention 双层配置" in koder
    assert "requireMention: true" in koder


def test_workspace_memory_templates_reference_memory_kickoff() -> None:
    claude = _read("core/templates/workspace-memory.template.md.claude")
    gemini = _read("core/templates/workspace-memory.template.md.gemini")

    assert "memory-kickoff.txt" in claude
    assert "memory-kickoff.txt" in gemini
    assert "ancestor-kickoff.txt" not in claude
    assert "ancestor-kickoff.txt" not in gemini
