from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_starter_profiles_manifest_path_is_real() -> None:
    assert (REPO / "examples" / "starter" / "profiles").is_dir()


def test_patrol_cron_contract_uses_patrol_daily_weekly_only() -> None:
    skill = (REPO / "core" / "skills" / "patrol" / "SKILL.md").read_text(encoding="utf-8")
    cron = (REPO / "core" / "skills" / "patrol" / "scripts" / "patrol_cron.sh").read_text(
        encoding="utf-8"
    )

    assert "daily or weekly" in skill
    assert '[[ "$mode" == "daily" || "$mode" == "weekly" ]]' in cron
    assert "project-patrol" not in cron
    assert "${project}-patrol" in cron


def test_qa_patrol_cron_references_are_gone() -> None:
    assert not (REPO / "core" / "skills" / "qa" / "scripts" / "qa_patrol_cron.sh").exists()
    for path in (
        REPO / "core" / "skills" / "patrol" / "SKILL.md",
        REPO / "core" / "templates" / "patrol.plist.in",
    ):
        assert "qa_patrol_cron.sh" not in path.read_text(encoding="utf-8")


def test_install_task_has_patrol_and_qa_compatibility_backlog_paths() -> None:
    tasks_root = Path.home() / ".agents" / "tasks" / "install"
    assert (tasks_root / "patrol" / "TODO.md").exists()
    assert (tasks_root / "qa" / "TODO.md").exists()
