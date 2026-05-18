from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_BUILDER_SKILL = _REPO / "core" / "skills" / "builder" / "SKILL.md"

_REQUIRED_KEYWORDS = ("worktree", "isolated", "clawseat/main", "不动 operator")


def test_builder_skills_contain_worktree_rule_keywords() -> None:
    text = _BUILDER_SKILL.read_text(encoding="utf-8").lower()
    for keyword in _REQUIRED_KEYWORDS:
        assert keyword in text, f"{_BUILDER_SKILL} must contain keyword: {keyword}"
