from __future__ import annotations

import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
INSTALL = REPO / "scripts" / "install.sh"
SKILL = REPO / "core" / "skills" / "clawseat-install" / "SKILL.md"


def test_clawseat_install_skill_lists_user_facing_install_flags() -> None:
    result = subprocess.run(["bash", str(INSTALL), "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    skill = SKILL.read_text(encoding="utf-8")
    for token in (
        "--project",
        "--repo-root",
        "--force-repo-root",
        "--template",
        "--memory-tool",
        "--memory-model",
        "--provider",
        "--all-api-provider",
        "--base-url",
        "--api-key",
        "--model",
        "--provision-keys",
        "--reinstall",
        "--uninstall",
        "--enable-auto-patrol",
        "--load-all-skills",
        "--detect-only",
        "--dry-run",
        "--reset-harness-memory",
    ):
        assert token in result.stdout
        assert token in skill


def test_clawseat_install_skill_lists_current_templates_only() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    for template in ("clawseat-creative", "clawseat-engineering", "clawseat-solo"):
        assert template in skill
    assert "clawseat-default" not in skill
    assert "clawseat-" + "minimal" not in skill
