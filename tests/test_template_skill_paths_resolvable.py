from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - Python <3.11 fallback
    import tomli as tomllib  # type: ignore[no-redef]


_REPO = Path(__file__).resolve().parents[1]
_ALLOWED_PREFIXES = (
    "~/.claude/skills/",
    "~/.agents/skills/",
    "{CLAWSEAT_ROOT}/",
)


def _skill_paths(value: Any) -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for child in value.values():
            paths.extend(_skill_paths(child))
        return paths
    if isinstance(value, list):
        paths: list[str] = []
        for child in value:
            paths.extend(_skill_paths(child))
        return paths
    if isinstance(value, str) and value.endswith("/SKILL.md"):
        return [value]
    return []


def test_template_skill_paths_use_standard_homes() -> None:
    """Template skill refs must use ClawSeat or mirrored tool skill homes."""
    bad_refs: list[str] = []
    for toml_path in sorted((_REPO / "templates").glob("*.toml")):
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        for skill_ref in _skill_paths(data):
            if not skill_ref.startswith(_ALLOWED_PREFIXES):
                bad_refs.append(f"{toml_path.relative_to(_REPO)}: {skill_ref}")

    assert not bad_refs, "bad template skill paths:\n" + "\n".join(bad_refs)
