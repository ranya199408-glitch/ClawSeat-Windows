from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BRIEF_TEMPLATE = _REPO / "core" / "templates" / "memory-bootstrap.template.md"
_SKILL = _REPO / "core" / "skills" / "memory-oracle" / "references" / "memory-operations-policy.md"


def test_ancestor_brief_template_has_pyramid_l2_l3_boundary_and_bootstrap_preflight() -> None:
    text = _BRIEF_TEMPLATE.read_text(encoding="utf-8")

    assert "### B3.5.0 — pre-flight: 确认 project 已 bootstrap" in text
    assert "agent_admin.py project show ${PROJECT_NAME}" in text
    assert "agent_admin.py project bootstrap --template {CLAWSEAT_TEMPLATE_NAME}" in text
    assert "agent_admin.py project use ${PROJECT_NAME}" in text
    assert "smoke01" in text
    assert "L2/L3 边界" in text
    assert "agent-launcher.sh" in text
    assert "ARCH-CLARITY-047" in text
    assert "绕过 L2 直接调 launcher" in text


def test_ancestor_skill_has_pyramid_l2_l3_boundary_and_bootstrap_preflight() -> None:
    text = _SKILL.read_text(encoding="utf-8")

    assert "B3.5.0-bootstrap-preflight" in text
    assert "agent_admin project show ${PROJECT_NAME}" in text
    assert "bootstrap + project use" in text
    assert "smoke01 / pre-SPAWN-049 legacy project" in text
    assert "### 6.5 L2/L3 Pyramid 边界" in text
    assert "ARCH-CLARITY-047 §3z" in text
