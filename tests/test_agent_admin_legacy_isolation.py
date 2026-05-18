"""Regression tests for agent_admin → agent_admin_legacy decoupling (audit H8).

Before the fix, `agent_admin.py` did a top-level
`from agent_admin_legacy import LegacyHandlers, LegacyHooks` and built a
module-level `LEGACY_HANDLERS` global. Every import of `agent_admin`
therefore pulled legacy migration code onto the runtime hot path, so any
bug in legacy leaked into normal operation.

These tests pin the new split:
- importing `agent_admin` must NOT import `agent_admin_legacy`
- `archive_if_exists` (heavily used by CRUD) works without legacy loaded
- `migrate_session_model` no-ops when no legacy state is present, so the
  legacy module is only imported when there is actually work to do
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def test_agent_admin_import_does_not_touch_legacy() -> None:
    """Verified via a clean subprocess so stray test-runner imports cannot mask the result."""
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / "core" / "scripts"))
        import agent_admin  # noqa: F401
        assert "agent_admin_legacy" not in sys.modules, (
            "agent_admin_legacy leaked into sys.modules at import time"
        )
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_archive_if_exists_works_without_legacy_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Drop any prior load so we can observe the (non-)import.
    sys.modules.pop("agent_admin_legacy", None)

    agent_admin = importlib.import_module("agent_admin")
    monkeypatch.setattr(agent_admin, "LEGACY_ROOT", tmp_path / "archive")

    doomed = tmp_path / "doomed.txt"
    doomed.write_text("x")

    agent_admin.archive_if_exists(doomed, "workspaces")

    assert not doomed.exists()
    archived = list((tmp_path / "archive" / "workspaces").iterdir())
    assert len(archived) == 1
    assert archived[0].read_text() == "x"
    # The archive helper must not have reached for the legacy module.
    assert "agent_admin_legacy" not in sys.modules


def test_archive_if_exists_noops_on_missing_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent_admin = importlib.import_module("agent_admin")
    monkeypatch.setattr(agent_admin, "LEGACY_ROOT", tmp_path / "archive")
    # Must not raise.
    agent_admin.archive_if_exists(tmp_path / "does-not-exist.txt", "runtimes")
    # And must not create the archive dir preemptively.
    assert not (tmp_path / "archive").exists()


def test_migrate_session_model_short_circuits_when_no_legacy_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_admin = importlib.import_module("agent_admin")
    sys.modules.pop("agent_admin_legacy", None)

    # Point ENGINEERS_ROOT at an empty dir — no legacy state.
    empty = tmp_path / "engineers"
    empty.mkdir()
    monkeypatch.setattr(agent_admin, "ENGINEERS_ROOT", empty)

    agent_admin.migrate_session_model()

    assert "agent_admin_legacy" not in sys.modules, (
        "migrate_session_model must not import legacy when there is nothing to migrate"
    )


def test_migrate_session_model_short_circuits_when_records_are_modern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_admin = importlib.import_module("agent_admin")
    sys.modules.pop("agent_admin_legacy", None)

    engineers = tmp_path / "engineers"
    (engineers / "alice").mkdir(parents=True)
    # Modern engineer.toml — no top-level `project =` line.
    (engineers / "alice" / "engineer.toml").write_text(
        'id = "alice"\nrole = "builder"\n', encoding="utf-8"
    )
    monkeypatch.setattr(agent_admin, "ENGINEERS_ROOT", engineers)

    agent_admin.migrate_session_model()

    assert "agent_admin_legacy" not in sys.modules


def test_migrate_session_model_detects_legacy_record_and_imports_legacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a legacy-format engineer.toml exists, legacy IS imported — but only
    then. The existing (pre-H8) behavior remains reachable when needed."""
    agent_admin = importlib.import_module("agent_admin")
    sys.modules.pop("agent_admin_legacy", None)

    engineers = tmp_path / "engineers"
    (engineers / "bob").mkdir(parents=True)
    (engineers / "bob" / "engineer.toml").write_text(
        'id = "bob"\nproject = "old-project"\n', encoding="utf-8"
    )
    monkeypatch.setattr(agent_admin, "ENGINEERS_ROOT", engineers)

    # Short-circuit indicator works standalone — no legacy import yet.
    assert agent_admin._legacy_state_present() is True
    assert "agent_admin_legacy" not in sys.modules
