from pathlib import Path


def test_planner_gemini_compat_notes_exist_and_complete() -> None:
    """gemini-compat-notes.md exists and all 4 compat points are documented."""
    notes = Path("core/skills/planner/references/gemini-compat-notes.md").read_text(encoding="utf-8")
    for point in ["frontmatter", "Claude-specific", "CLAWSEAT_ROOT", "subprocess"]:
        assert point.lower() in notes.lower(), f"Missing compat point: {point}"
    assert "known-divergence-blocker" not in notes
