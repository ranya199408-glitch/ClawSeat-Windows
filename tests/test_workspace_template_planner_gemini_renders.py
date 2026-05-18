from pathlib import Path


def test_workspace_template_planner_gemini_renders() -> None:
    """workspace-planner.template.md.gemini exists and planner SKILL.md path is resolvable."""
    repo = Path(__file__).resolve().parents[1]
    template = repo / "core" / "templates" / "workspace-planner.template.md.gemini"
    assert template.exists(), "workspace-planner.template.md.gemini missing"
    content = template.read_text(encoding="utf-8")
    assert "planner" in content.lower()
    assert "SKILL.md" in content
    rendered = content.replace("{{clawseat_root}}", str(repo))
    skill_path = repo / "core" / "skills" / "planner" / "SKILL.md"
    assert str(skill_path) in rendered
    assert skill_path.exists()
