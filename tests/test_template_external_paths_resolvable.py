from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


REPO = Path(__file__).resolve().parents[1]


def _skill_refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        refs: list[str] = []
        for child in value.values():
            refs.extend(_skill_refs(child))
        return refs
    if isinstance(value, list):
        refs: list[str] = []
        for child in value:
            refs.extend(_skill_refs(child))
        return refs
    if isinstance(value, str) and value.endswith("/SKILL.md"):
        return [value]
    return []


def _resolve(ref: str) -> Path:
    return Path(ref.replace("{CLAWSEAT_ROOT}", str(REPO))).expanduser()


def test_template_external_skill_paths_resolve_or_have_graceful_fallback() -> None:
    missing: list[str] = []
    for template in sorted((REPO / "templates").glob("*.toml")):
        text = template.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        for ref in _skill_refs(data):
            if _resolve(ref).exists():
                continue
            if "graceful-fallback" in text:
                continue
            missing.append(f"{template.relative_to(REPO)}: {ref}")

    assert not missing, "unresolvable template skill refs:\n" + "\n".join(missing)
