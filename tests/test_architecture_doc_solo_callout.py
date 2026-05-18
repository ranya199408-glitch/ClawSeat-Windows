from pathlib import Path


def test_architecture_has_solo_callout() -> None:
    """ARCHITECTURE.md contains clawseat-solo 3-seat callout."""
    content = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    heading = "### Solo Template (Minimal 3-Seat)"
    assert heading in content
    idx = content.index(heading)
    section = content[idx:idx + 800]
    assert any(word in section.lower() for word in ["3-seat", "minimal", "three-seat"])
    for seat in ["memory", "builder", "planner"]:
        assert seat in section, f"Solo callout missing seat: {seat}"
