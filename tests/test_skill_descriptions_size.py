from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_MIN_DESCRIPTION_WORDS = 30
_MAX_DESCRIPTION_WORDS = 200


def _frontmatter_description(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path} is missing frontmatter"
    end = text.find("\n---", 4)
    assert end != -1, f"{path} frontmatter is not closed"
    lines = text[4:end].splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("description:"):
            continue
        value = line.split(":", 1)[1].strip()
        if value in {">", "|"}:
            block: list[str] = []
            for follow in lines[index + 1 :]:
                if not follow.startswith("  "):
                    break
                block.append(follow.strip())
            return " ".join(block)
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        return value
    raise AssertionError(f"{path} frontmatter has no description")


def test_clawseat_skill_descriptions_fit_skill_creator_budget() -> None:
    skill_files = sorted(
        path
        for path in (_REPO / "core" / "skills").glob("clawseat*/SKILL.md")
        if not path.is_symlink()
    )
    assert skill_files

    for path in skill_files:
        description = _frontmatter_description(path)
        assert description
        words = len(description.split())
        assert _MIN_DESCRIPTION_WORDS <= words <= _MAX_DESCRIPTION_WORDS, (
            f"{path} description has {words} words: {description}"
        )
        assert "use when" in description.lower()
        assert "do not use for" in description.lower()
