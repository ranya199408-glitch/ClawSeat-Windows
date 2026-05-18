"""C4 tests: runtime HOME symlink auto-provisioning."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))

from runtime_home_links import (  # noqa: E402
    RUNTIME_HOME_LINK_NAMES,
    ensure_runtime_home_links,
)


def _make_pair(tmp_path: Path) -> tuple[Path, Path]:
    sandbox = tmp_path / "sandbox" / "home"
    real = tmp_path / "real_home"
    sandbox.mkdir(parents=True)
    real.mkdir()
    return sandbox, real


def _seed_real(real: Path, *names: str) -> None:
    for name in names:
        (real / name).mkdir()


# ── Happy path ────────────────────────────────────────────────────────


def test_creates_symlinks_for_existing_real_targets(tmp_path):
    sandbox, real = _make_pair(tmp_path)
    _seed_real(real, ".lark-cli", ".openclaw")

    result = ensure_runtime_home_links(sandbox, real)

    statuses = {a.name: a.status for a in result.actions}
    assert statuses == {".lark-cli": "created", ".openclaw": "created"}
    for name in (".lark-cli", ".openclaw"):
        link = sandbox / name
        assert link.is_symlink()
        assert link.readlink() == real / name
    assert not result.errors


def test_idempotent_re_run_no_op(tmp_path):
    sandbox, real = _make_pair(tmp_path)
    _seed_real(real, ".lark-cli", ".openclaw")

    ensure_runtime_home_links(sandbox, real)  # first pass
    second = ensure_runtime_home_links(sandbox, real)

    statuses = {a.name: a.status for a in second.actions}
    assert all(s == "already_correct" for s in statuses.values())


# ── Defensive paths ───────────────────────────────────────────────────


def test_skips_when_real_target_missing(tmp_path):
    sandbox, real = _make_pair(tmp_path)
    # Only seed .lark-cli on the real side, leave .openclaw missing.
    _seed_real(real, ".lark-cli")

    result = ensure_runtime_home_links(sandbox, real)

    statuses = {a.name: a.status for a in result.actions}
    assert statuses[".lark-cli"] == "created"
    assert statuses[".openclaw"] == "skipped_missing_source"
    # Crucially: no dangling symlink for the missing source.
    assert not (sandbox / ".openclaw").exists()
    assert not (sandbox / ".openclaw").is_symlink()


def test_leaves_real_directory_alone(tmp_path):
    """If the operator has put a real `.lark-cli` directory in the sandbox,
    do NOT destroy it."""
    sandbox, real = _make_pair(tmp_path)
    _seed_real(real, ".lark-cli")
    existing = sandbox / ".lark-cli"
    existing.mkdir()
    (existing / "sentinel.txt").write_text("keep me")

    result = ensure_runtime_home_links(sandbox, real)

    statuses = {a.name: a.status for a in result.actions}
    assert statuses[".lark-cli"] == "skipped_real_target"
    # Real dir intact; sentinel file still there.
    assert existing.is_dir() and not existing.is_symlink()
    assert (existing / "sentinel.txt").read_text() == "keep me"


def test_repairs_wrong_symlink(tmp_path):
    """A symlink pointing somewhere else is fixed in place."""
    sandbox, real = _make_pair(tmp_path)
    _seed_real(real, ".lark-cli")
    bogus_target = tmp_path / "bogus_target"
    bogus_target.mkdir()
    (sandbox / ".lark-cli").symlink_to(bogus_target)

    result = ensure_runtime_home_links(sandbox, real)

    statuses = {a.name: a.status for a in result.actions}
    assert statuses[".lark-cli"] == "fixed"
    link = sandbox / ".lark-cli"
    assert link.is_symlink()
    assert link.readlink() == real / ".lark-cli"


def test_sandbox_equals_real_skips(tmp_path):
    """When sandbox_home IS the real home (no isolation), no symlinks
    are created — just report already_correct."""
    real = tmp_path / "shared_home"
    real.mkdir()
    _seed_real(real, ".lark-cli", ".openclaw")

    result = ensure_runtime_home_links(real, real)

    assert all(a.status == "already_correct" for a in result.actions)
    # And we did not accidentally create nested links.
    for name in (".lark-cli", ".openclaw"):
        link = real / name
        assert link.is_dir() and not link.is_symlink()


def test_custom_names(tmp_path):
    sandbox, real = _make_pair(tmp_path)
    (real / ".config").mkdir()

    result = ensure_runtime_home_links(sandbox, real, names=[".config"])

    statuses = {a.name: a.status for a in result.actions}
    assert statuses == {".config": "created"}
    assert (sandbox / ".config").is_symlink()


def test_canonical_names_are_lark_cli_and_openclaw():
    """Guard against accidental reordering or renaming of the canonical
    list; callers depend on these two names specifically."""
    assert set(RUNTIME_HOME_LINK_NAMES) >= {".lark-cli", ".openclaw"}
