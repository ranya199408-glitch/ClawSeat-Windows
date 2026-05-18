from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _tracked_helper_definitions(helper_name: str) -> list[Path]:
    pattern = "def " + helper_name + "("
    matches: list[Path] = []
    skip_dirs = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", "node_modules"}
    for path in REPO_ROOT.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if pattern in text:
            matches.append(path.relative_to(REPO_ROOT))
    return sorted(matches)


def test_now_iso_single_source():
    matches = _tracked_helper_definitions("now_iso")
    assert Path("core/lib/utils.py") in matches
    assert len(matches) <= 2, matches


def test_load_toml_single_source():
    matches = _tracked_helper_definitions("load_toml")
    assert matches == [Path("core/lib/utils.py")]
