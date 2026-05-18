from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_migrate_profile_to_v2_file_does_not_exist() -> None:
    assert not (REPO / "core" / "scripts" / "migrate_profile_to_v2.py").exists()
