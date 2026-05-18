from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
LIB = REPO / "core" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

from profile_validator import validate_profile_v2  # noqa: E402


def _write_profile(path: Path, seats: list[str]) -> None:
    rendered = ", ".join(f'"{seat}"' for seat in seats)
    path.write_text(
        "version = 2\n"
        f"seats = [{rendered}]\n"
        'openclaw_frontstage_agent = "yu"\n',
        encoding="utf-8",
    )


def test_v2_profile_memory_primary_passes_validator(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _write_profile(path, ["memory", "planner", "builder"])

    result = validate_profile_v2(path)

    assert result.ok
    assert result.errors == []


def test_v1_profile_ancestor_primary_passes_validator(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _write_profile(path, ["ancestor", "planner", "builder"])

    result = validate_profile_v2(path)

    assert result.ok
    assert result.errors == []


def test_profile_missing_primary_fails_validator(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _write_profile(path, ["planner", "builder"])

    result = validate_profile_v2(path)

    assert not result.ok
    assert any("primary seat" in error for error in result.errors)


def test_profile_missing_planner_fails_validator(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _write_profile(path, ["memory", "builder"])

    result = validate_profile_v2(path)

    assert not result.ok
    assert any("planner" in error for error in result.errors)


def test_profile_with_both_primary_aliases_passes_validator(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _write_profile(path, ["memory", "ancestor", "planner"])

    result = validate_profile_v2(path)

    assert result.ok
    assert result.errors == []


def test_koder_seat_still_fails_validator(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    _write_profile(path, ["memory", "planner", "koder"])

    result = validate_profile_v2(path)

    assert not result.ok
    assert any("koder" in error for error in result.errors)
