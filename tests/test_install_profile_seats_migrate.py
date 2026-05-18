from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from migrate_ancestor_paths import migrate_install_profile_seats, patch_profile  # noqa: E402


def test_migrate_install_profile_seats_v07_to_v2(tmp_path: Path) -> None:
    profile = tmp_path / "install-profile-dynamic.toml"
    profile.write_text(
        'seats = ["memory", "koder", "planner", "builder-1", "reviewer-1"]\n'
        'heartbeat_owner = "koder"\n'
        'heartbeat_seats = ["koder"]\n'
        'materialized_seats = ["memory", "koder", "planner", "builder-1", "reviewer-1"]\n'
        'bootstrap_seats = ["koder"]\n'
        "\n"
        "[seat_overrides.builder-1]\n"
        'tool = "claude"\n'
        'auth_mode = "oauth"\n'
        "\n"
        "[seat_overrides.reviewer-1]\n"
        'provider = "anthropic"\n',
        encoding="utf-8",
    )

    assert migrate_install_profile_seats(profile)

    updated = profile.read_text(encoding="utf-8")
    assert 'seats = ["memory", "planner", "builder", "reviewer"]' in updated
    assert 'materialized_seats = ["memory", "planner", "builder", "reviewer"]' in updated
    assert 'bootstrap_seats = []' in updated
    assert 'heartbeat_seats = []' in updated
    assert 'heartbeat_owner = ""' in updated
    assert "[seat_overrides.builder-1]\n" in updated
    assert "[seat_overrides.reviewer-1]\n" in updated
    assert list(tmp_path.glob("install-profile-dynamic.toml.bak.*"))


def test_migrate_install_profile_seats_is_idempotent(tmp_path: Path) -> None:
    profile = tmp_path / "install-profile-dynamic.toml"
    profile.write_text(
        'seats = ["memory", "planner", "builder", "reviewer"]\n'
        'heartbeat_owner = ""\n'
        'heartbeat_seats = []\n'
        'bootstrap_seats = []\n',
        encoding="utf-8",
    )

    assert not migrate_install_profile_seats(profile)

    assert not list(tmp_path.glob("install-profile-dynamic.toml.bak.*"))


def test_migrate_install_profile_seats_preserves_non_target_lists(tmp_path: Path) -> None:
    profile = tmp_path / "install-profile-dynamic.toml"
    profile.write_text(
        'seats = ["memory", "koder", "planner", "builder-1"]\n'
        'default_start_seats = ["builder-1"]\n',
        encoding="utf-8",
    )

    assert migrate_install_profile_seats(profile)

    updated = profile.read_text(encoding="utf-8")
    assert 'seats = ["memory", "planner", "builder"]' in updated
    assert 'default_start_seats = ["builder-1"]' in updated


def test_patch_profile_runs_install_seat_and_loop_migrations(tmp_path: Path) -> None:
    profile = tmp_path / "install-profile-dynamic.toml"
    profile.write_text(
        'seats = ["memory", "koder", "planner", "builder-1"]\n'
        'heartbeat_owner = "koder"\n'
        'bootstrap_seats = ["koder"]\n'
        'active_loop_owner = "planner"\n'
        'default_notify_target = "planner"\n',
        encoding="utf-8",
    )
    changed: list[str] = []

    patch_profile(profile, changed)

    updated = profile.read_text(encoding="utf-8")
    assert 'seats = ["memory", "planner", "builder"]' in updated
    assert 'heartbeat_owner = ""' in updated
    assert 'bootstrap_seats = []' in updated
    assert 'active_loop_owner = "memory"' in updated
    assert 'default_notify_target = "memory"' in updated
    assert any("install profile seats" in item for item in changed)


def test_migrate_install_profile_seats_deduplicates_renamed_singletons(tmp_path: Path) -> None:
    profile = tmp_path / "install-profile-dynamic.toml"
    profile.write_text(
        'seats = ["memory", "planner", "builder", "builder-1", "reviewer", "reviewer-1"]\n',
        encoding="utf-8",
    )

    assert migrate_install_profile_seats(profile)

    assert (
        'seats = ["memory", "planner", "builder", "reviewer"]'
        in profile.read_text(encoding="utf-8")
    )
