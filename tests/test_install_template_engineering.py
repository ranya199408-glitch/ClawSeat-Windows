from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "templates" / "clawseat-engineering.toml"
WORKSPACE_REVIEWER_TEMPLATE = REPO / "core" / "templates" / "workspace-reviewer.template.md"


def _engineering() -> dict:
    with TEMPLATE.open("rb") as handle:
        return tomllib.load(handle)


def test_engineering_template_has_five_memory_primary_seats() -> None:
    data = _engineering()
    assert data["defaults"]["window_mode"] == "split-2"
    assert data["defaults"]["monitor_max_panes"] == 5
    assert [seat["id"] for seat in data["engineers"]] == [
        "memory",
        "planner",
        "builder",
        "reviewer",
        "patrol",
    ]
    assert "QA + visual review" in data["description"]


def test_engineering_template_reviewer_is_independent_claude_oauth() -> None:
    reviewer = next(seat for seat in _engineering()["engineers"] if seat["id"] == "reviewer")
    assert reviewer["role"] == "code-reviewer"
    assert reviewer["tool"] == "claude"
    assert reviewer["auth_mode"] == "oauth"
    assert reviewer["provider"] == "anthropic"
    assert reviewer["review_authority"] is True


def test_engineering_template_reviewer_is_qa_visual_authority() -> None:
    reviewer = next(seat for seat in _engineering()["engineers"] if seat["id"] == "reviewer")
    assert reviewer["design_authority"] is True
    assert (
        reviewer["role_details"]
        == [
            "independent code/QA/visual review gate; browser QA testing, visual consistency check, diff review; emits Verdict before planner accepts delivery",
        ]
    )


def test_workspace_reviewer_template_exists_with_review_modes() -> None:
    assert WORKSPACE_REVIEWER_TEMPLATE.exists()
    text = WORKSPACE_REVIEWER_TEMPLATE.read_text(encoding="utf-8")
    for section in (
        "## Diff review",
        "## QA Testing Mode (browser / multimodal)",
        "## Visual Review Mode (layout/spacing/color/component consistency)",
    ):
        assert section in text
    for placeholder in (
        "{{project}}",
        "{{repo_root}}",
        "{{agents_home}}",
        "{{clawseat_root}}",
        "{{workspace}}",
    ):
        assert placeholder in text


def test_engineering_template_builder_and_patrol_are_cross_tool() -> None:
    seats = {seat["id"]: seat for seat in _engineering()["engineers"]}
    assert seats["builder"]["tool"] == "codex"
    assert seats["builder"]["provider"] == "openai"
    assert seats["patrol"]["tool"] == "claude"
    assert seats["patrol"]["provider"] == "minimax"
