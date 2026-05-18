from pathlib import Path
import re


def test_intent_md_patrol_skills_consistent() -> None:
    """patrol-1 skill list in table matches bullet list in intent.md."""
    content = Path("core/templates/shared/TOOLS/intent.md").read_text(encoding="utf-8")
    table_row = re.search(r"\|\s*`?patrol-1`?\s*\|[^|]*\|([^|]+)\|", content)
    bullet = re.search(r"`?patrol-1`?:\s*([^\n]+)", content)
    if table_row and bullet:
        table_skills = {s.strip().strip("`") for s in table_row.group(1).split(",")}
        bullet_skills = {s.strip() for s in bullet.group(1).split(",")}
        assert table_skills == bullet_skills, (
            f"patrol-1 skills inconsistent: table={table_skills} vs bullet={bullet_skills}"
        )
    else:
        assert "qa-test" not in content or "gstack-qa" in content
