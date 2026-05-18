from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SKILLS = [
    "builder",
    "designer",
    "patrol",
    "reviewer",
]


def _skill_text(skill: str) -> str:
    return (_REPO / "core" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")


def test_specialist_skills_require_complete_handoff_receipt_two_step() -> None:
    for skill in _SKILLS:
        text = _skill_text(skill)
        assert "complete_handoff.py" in text, skill
        assert "两步" in text or "two-step" in text.lower(), skill
        assert "不可二选一" in text or "not optional" in text.lower(), skill
        assert "cannot substitute" in text, skill
        assert "or `complete_handoff.py`" not in text, skill
        assert "or the `complete_handoff.py` helper" not in text, skill


def test_patrol_handoff_receipt_rule_is_task_only_not_cron_finding_path() -> None:
    text = _skill_text("patrol")
    assert "workflow.md 派工 task" in text
    assert "cron-driven scan" in text
    assert "[PATROL-NOTIFY]" in text


def test_workspace_renderer_does_not_emit_complete_handoff_as_optional_alternative() -> None:
    text = (_REPO / "core" / "scripts" / "agent_admin_workspace.py").read_text(encoding="utf-8")
    assert "or the `complete_handoff.py` helper" not in text
    assert "call `complete_handoff.py` to write the durable receipt" in text
    assert "send-and-verify is wake-up only and cannot substitute" in text
