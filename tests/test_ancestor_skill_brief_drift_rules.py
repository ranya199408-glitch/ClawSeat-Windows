from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "memory-brief-mtime-check.sh"
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"
_INSTALL = _REPO / "scripts" / "install.sh"
_PROJECT_LIB = _REPO / "scripts" / "install" / "lib" / "project.sh"


def test_drift_check_script_exists_and_is_executable() -> None:
    assert _SCRIPT.is_file()
    assert _SCRIPT.stat().st_mode & 0o111


def test_skill_and_install_guide_document_brief_drift_handling() -> None:
    skill_text = _SKILL.read_text(encoding="utf-8")
    install_text = _INSTALL.read_text(encoding="utf-8") + _PROJECT_LIB.read_text(encoding="utf-8")

    assert "Brief drift 自检" in skill_text
    assert "bash ${CLAWSEAT_ROOT}/scripts/memory-brief-mtime-check.sh" in skill_text
    assert "BRIEF_DRIFT_DETECTED" in skill_text
    assert "Brief immutability" in skill_text
    assert "no hot-reload" in skill_text or "hot-reload" in skill_text

    assert "## 如果 ${PRIMARY_SEAT_ID} seat 报 BRIEF_DRIFT_DETECTED" in install_text
    assert "${PRIMARY_SEAT_ID} seat 在每个 B 步开始前会先跑 brief drift check hook" in install_text
    assert "tmux kill-session -t ${primary_session_name}" in install_text
    assert "continue" in install_text or "继续" in install_text
