from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


REPO = Path(__file__).resolve().parents[1]


def _load(path: str) -> dict[str, Any]:
    return tomllib.loads((REPO / path).read_text(encoding="utf-8"))


def _iter_manifest_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        paths: list[str] = []
        for child in value:
            paths.extend(_iter_manifest_paths(child))
        return paths
    if isinstance(value, dict):
        if "path" in value:
            return [str(value["path"])]
        paths: list[str] = []
        for child in value.values():
            paths.extend(_iter_manifest_paths(child))
        return paths
    return []


def test_manifest_version_matches_pyproject() -> None:
    manifest = _load("manifest.toml")
    pyproject = _load("pyproject.toml")

    assert manifest["version"] == pyproject["project"]["version"]


def test_manifest_templates_match_template_files() -> None:
    manifest = _load("manifest.toml")
    expected = {path.stem for path in (REPO / "templates").glob("clawseat-*.toml")}

    assert set(manifest["templates"]) == expected


def test_manifest_declared_paths_exist() -> None:
    manifest = _load("manifest.toml")
    missing = []
    for section in ("modules", "templates", "entrypoints"):
        for rel in _iter_manifest_paths(manifest[section]):
            if not (REPO / rel).exists():
                missing.append(f"{section}: {rel}")

    assert not missing, "manifest references missing paths:\n" + "\n".join(missing)
