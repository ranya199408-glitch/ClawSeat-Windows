from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_INSTALL = _REPO / "scripts" / "install.sh"
_SELF_UPDATE_LIB = _REPO / "scripts" / "install" / "lib" / "self_update.sh"


def _install_text() -> str:
    return _INSTALL.read_text(encoding="utf-8") + _SELF_UPDATE_LIB.read_text(encoding="utf-8")


def test_self_update_detects_stale_workspace_sha() -> None:
    text = _install_text()

    assert "stale_workspace_projects()" in text
    assert "rendered_from_clawseat_sha" in text
    assert "ClawSeat updated %s..%s. %d project(s) have stale workspaces" in text


def test_self_update_rerender_prompt_dry_run() -> None:
    text = _install_text()

    assert "Run regenerate-workspace --all-seats now? (Y/n)" in text
    assert "engineer regenerate-workspace --project \"$project_name\" --all-seats --yes" in text
    assert "workspace re-render failed for $project_name (non-fatal)" in text
    assert "workspace re-render skipped in non-interactive mode" in text
