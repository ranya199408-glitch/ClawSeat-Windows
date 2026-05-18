"""Regression tests for the three real bugs + operational-hazard
narrowings identified in the second-pass audit (H9/H10/H11 + M14-M16).

Each invariant pinned so the bug can't silently regress.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ── H9: _profile_snapshot cleans up its temp file ────────────────────


def test_profile_snapshot_removes_temp_file_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a successful snapshot the temp file that carried the
    profile path into the subprocess must be unlinked. Before the fix
    these accumulated forever under /tmp/."""
    from core.adapter.clawseat_adapter import ClawseatAdapter

    # Redirect tempfile directory so we can observe what lives there.
    tempdir = tmp_path / "tmp"
    tempdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tempdir))
    monkeypatch.setattr(tempfile, "tempdir", str(tempdir))

    adapter = ClawseatAdapter(repo_root=_REPO, python_bin=sys.executable)

    # Stub out _run so we don't actually shell out.
    from core.adapter._adapter_types import AdapterResult

    def _fake_run(cmd: list[str]) -> AdapterResult:
        return AdapterResult(
            command=cmd,
            returncode=0,
            stdout='{"profile_path":"/x","project_name":"p","tasks_root":"/x","planner_brief_path":"/x","active_loop_owner":"koder","heartbeat_owner":"koder","planner_instance":"koder","seats":["koder"]}',
            stderr="",
        )

    monkeypatch.setattr(adapter, "_run", _fake_run)

    before = set(tempdir.iterdir())
    adapter._profile_snapshot(tmp_path / "fake.toml")
    after = set(tempdir.iterdir())

    assert after == before, f"temp files leaked: {after - before}"


def test_profile_snapshot_removes_temp_file_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Even when the helper subprocess fails, the temp file must be removed."""
    from core.adapter.clawseat_adapter import ClawseatAdapter
    from core.adapter._adapter_types import AdapterResult

    tempdir = tmp_path / "tmp"
    tempdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tempdir))
    monkeypatch.setattr(tempfile, "tempdir", str(tempdir))

    adapter = ClawseatAdapter(repo_root=_REPO, python_bin=sys.executable)

    def _fake_run(cmd: list[str]) -> AdapterResult:
        return AdapterResult(command=cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr(adapter, "_run", _fake_run)

    before = set(tempdir.iterdir())
    with pytest.raises(RuntimeError):
        adapter._profile_snapshot(tmp_path / "fake.toml")
    after = set(tempdir.iterdir())

    assert after == before, f"temp files leaked on failure path: {after - before}"


# ── H10: create_repo_symlink validates the target ────────────────────


def _make_instance(workspace: Path, repo_root: Path) -> SimpleNamespace:
    return SimpleNamespace(workspace=workspace, repo_root=repo_root)


def test_create_repo_symlink_replaces_stale_link(tmp_path: Path) -> None:
    from core.engine.instantiate_seat import create_repo_symlink

    old_repo = tmp_path / "old-repo"
    old_repo.mkdir()
    new_repo = tmp_path / "new-repo"
    new_repo.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    # Pre-create a link pointing at the old repo — the pre-fix code
    # would short-circuit on this and leave the seat reading stale code.
    (workspace / "repos").mkdir()
    (workspace / "repos" / "repo").symlink_to(old_repo)

    create_repo_symlink(_make_instance(workspace, new_repo))

    resolved = (workspace / "repos" / "repo").resolve()
    assert resolved == new_repo.resolve(), f"expected {new_repo}, got {resolved}"


def test_create_repo_symlink_noops_when_already_correct(tmp_path: Path) -> None:
    from core.engine.instantiate_seat import create_repo_symlink

    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()

    create_repo_symlink(_make_instance(workspace, repo))
    link = workspace / "repos" / "repo"
    first_inode = os.lstat(link).st_ino

    # Second call must not recreate the link (inode preserved).
    create_repo_symlink(_make_instance(workspace, repo))
    second_inode = os.lstat(link).st_ino

    assert first_inode == second_inode, "link was recreated unnecessarily"


def test_create_repo_symlink_refuses_to_overwrite_regular_file(tmp_path: Path) -> None:
    from core.engine.instantiate_seat import create_repo_symlink

    repo = tmp_path / "repo"
    repo.mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    repos = workspace / "repos"
    repos.mkdir()
    # User put a real file there by hand — tool must refuse to clobber.
    (repos / "repo").write_text("user notes", encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to overwrite non-symlink"):
        create_repo_symlink(_make_instance(workspace, repo))


# ── H11: dynamic_profile_path is concurrency-safe ────────────────────


def _migration_worker(args: tuple[str, str, str]) -> str:
    """Worker: import resolve, force a migration, return the result path.
    Runs in a subprocess so each worker has an independent module state."""
    import os as _os

    legacy_path, target_dir, project = args
    _os.environ["HOME"] = target_dir
    # Shadow /tmp lookup by pointing resolve to our fabricated legacy.
    # We cannot change Path("/tmp") easily; instead pre-seed the
    # destination via the real legacy path the function already probes.
    import importlib
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    resolve = importlib.import_module("core.resolve")
    result = resolve.dynamic_profile_path(project)
    return str(result)


def test_dynamic_profile_path_migration_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent callers must observe a complete destination file — no
    half-written state, no duplicated work."""
    project = "racey-proj"
    legacy_src = Path("/tmp") / f"{project}-profile-dynamic.toml"

    # Write a reasonably large legacy source to maximise race window.
    payload = ("x" * 4096 + "\n") * 64  # ~260 KB
    legacy_src.write_text(payload, encoding="utf-8")

    # Redirect HOME so the destination lands under tmp_path.
    # dynamic_profile_path now resolves via real_user_home(), which
    # ignores plain HOME / Path.home() patches — use CLAWSEAT_REAL_HOME
    # (the supported test override) so the migration target redirects.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(fake_home))
    monkeypatch.delenv("CLAWSEAT_SANDBOX_HOME_STRICT", raising=False)
    monkeypatch.delenv("AGENT_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    # Ensure destination does not pre-exist.
    destination = fake_home / ".agents" / "profiles" / f"{project}-profile-dynamic.toml"
    assert not destination.exists()

    # Fire N threads that all race to migrate.
    from core import resolve

    results: list[Path] = []
    errors: list[BaseException] = []

    def _go() -> None:
        try:
            results.append(resolve.dynamic_profile_path(project))
        except BaseException as exc:  # pragma: no cover — racing threads
            errors.append(exc)

    threads = [threading.Thread(target=_go) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    try:
        assert not errors, errors
        # Every thread gets the same persistent path back.
        assert all(r == destination for r in results), results
        # Destination contents are identical to source (no truncation).
        assert destination.read_text(encoding="utf-8") == payload
        # No lingering .tmp file left behind.
        stray = list(destination.parent.glob("*.tmp"))
        assert not stray, f"stray partial file: {stray}"
    finally:
        legacy_src.unlink(missing_ok=True)


# ── M14: drain_pending_ops narrows its exception handling ────────────


def test_drain_pending_ops_records_malformed_payload_clearly(tmp_path: Path) -> None:
    from core.adapter.clawseat_adapter import ClawseatAdapter, PendingProjectOperation

    adapter = ClawseatAdapter(repo_root=_REPO, python_bin=sys.executable)
    adapter.current_project = "proj"

    bad_op = PendingProjectOperation(
        kind="notify",
        project_name="proj",
        frontstage_epoch=0,
        profile_path="/does-not-exist.toml",
        payload={},  # intentionally missing keys
    )
    adapter._pending_inbox["proj"] = [bad_op]
    results = adapter.drain_pending_ops(project_name="proj")

    assert len(results) == 1
    err = results[0].stderr
    assert "malformed payload" in err or "notify failed" in err
    # The queue must retain the failed op for retry after a code fix.
    assert len(adapter._pending_inbox["proj"]) == 1


# ── M15: tmux has-session call has a timeout ────────────────────────


def test_check_session_tolerates_hanging_tmux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When tmux has-session wedges, check_session must still return a
    well-formed SessionStatus (running=False) instead of blocking."""
    from core.adapter import clawseat_adapter as mod

    fake_sessions = tmp_path / "sessions"
    (fake_sessions / "proj" / "s1").mkdir(parents=True)
    (fake_sessions / "proj" / "s1" / "session.toml").write_text(
        'session = "proj-s1-claude"\n'
        'tool = "claude"\n'
        'provider = "anthropic"\n'
        'auth_mode = "oauth"\n'
        'runtime_dir = "/tmp/rt"\n'
        'workspace = "/tmp/ws"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SESSIONS_ROOT", str(fake_sessions))

    import subprocess as _sp

    def _boom(*args, **kwargs):
        raise _sp.TimeoutExpired(cmd=args[0] if args else "tmux", timeout=5)

    monkeypatch.setattr(mod.subprocess, "run", _boom)

    adapter = mod.ClawseatAdapter(repo_root=_REPO, python_bin=sys.executable)
    status = adapter.check_session(project_name="proj", seat_id="s1")
    assert status.exists is True
    assert status.tmux_running is False


# ── M16: bootstrap_receipt subprocess calls have timeouts ───────────


def test_bootstrap_receipt_subprocess_calls_pass_timeout() -> None:
    """Regression guard: every subprocess.run invocation inside
    bootstrap_receipt.write_receipt must carry a timeout so a wedged
    tmux / python cannot stall the bootstrap."""
    import re

    source = (_REPO / "core" / "bootstrap_receipt.py").read_text(encoding="utf-8")
    run_calls = re.findall(r"subprocess\.run\s*\((.*?)\)", source, flags=re.DOTALL)
    assert run_calls, "expected at least one subprocess.run in bootstrap_receipt.py"
    for call in run_calls:
        assert "timeout=" in call, f"subprocess.run missing timeout=: {call[:120]}"
