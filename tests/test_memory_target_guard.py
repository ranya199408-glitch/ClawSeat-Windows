"""T9: Block dispatch/notify scripts from targeting the memory seat.

Memory is a synchronous oracle — its Stop hook runs ``/clear`` after every
turn, so any TODO.md entry or tmux-notify text dispatched to it lands in a
pane whose LLM context is about to be wiped. Callers MUST use
``core/skills/memory-oracle/scripts/query_memory.py`` instead. The guard
lives in ``_common.assert_target_not_memory`` and is called early in
``main()`` of all four dispatch/notify entrypoints.

Contract under test
-------------------
- ``_common.assert_target_not_memory("memory", <tool>)`` exits 2 and prints
  a pointer to ``query_memory.py`` + ``memory-query-protocol.md`` on stderr.
- Non-memory targets are a no-op (return None, no SystemExit).
- Both legacy (``scripts/`` under ``gstack-harness``) and dynamic
  (``core/migration/``) entrypoints trip the guard BEFORE calling
  ``load_profile`` — i.e. the guard still fires with a bogus profile path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
_LEGACY_SCRIPTS = REPO / "core" / "skills" / "gstack-harness" / "scripts"
_MIGRATION = REPO / "core" / "migration"


def _load_module(name: str, path: Path, *, extra_sys_path: list[Path] | None = None):
    """Load a script by file path into a unique module name.

    Ensures the script's own dir is on sys.path so its imports (e.g.
    ``from _common import ...`` for legacy scripts, or
    ``from dynamic_common import ...`` for migration scripts) resolve.
    """
    paths = [path.parent]
    if extra_sys_path:
        paths.extend(extra_sys_path)
    added: list[str] = []
    for p in paths:
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
            added.append(s)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        # Leave sys.path intact for other tests; removal is optional since
        # we use unique module names.
        pass


@pytest.fixture(scope="module")
def common():
    return _load_module("t9_common", _LEGACY_SCRIPTS / "_common.py")


@pytest.fixture(scope="module")
def dispatch_legacy():
    return _load_module("t9_dispatch_legacy", _LEGACY_SCRIPTS / "dispatch_task.py")


@pytest.fixture(scope="module")
def notify_legacy():
    return _load_module("t9_notify_legacy", _LEGACY_SCRIPTS / "notify_seat.py")


@pytest.fixture(scope="module")
def dispatch_dynamic():
    return _load_module("t9_dispatch_dynamic", _MIGRATION / "dispatch_task_dynamic.py")


@pytest.fixture(scope="module")
def notify_dynamic():
    return _load_module("t9_notify_dynamic", _MIGRATION / "notify_seat_dynamic.py")


# ---------------------------------------------------------------------------
# Core guard behavior
# ---------------------------------------------------------------------------


def test_guard_rejects_memory_target(common, capsys):
    with pytest.raises(SystemExit) as excinfo:
        common.assert_target_not_memory("memory", "dispatch_task.py")
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "does not support --target memory" in err
    assert "synchronous oracle" in err
    assert "query_memory.py" in err
    assert "memory-query-protocol.md" in err
    assert "dispatch_task.py" in err  # caller tool name in message


def test_guard_allows_non_memory_targets(common):
    # Each is a no-op — raises nothing, returns None.
    for seat in ["planner", "builder-1", "reviewer-1", "qa-1", "designer-1", "koder"]:
        assert common.assert_target_not_memory(seat, "notify_seat.py") is None


def test_guard_does_not_match_memory_prefix(common):
    # Seats whose names happen to start with "memory" (future memory-2,
    # memory-adapter, etc.) should NOT trip the guard — only exact match.
    assert common.assert_target_not_memory("memory-2", "dispatch_task.py") is None
    assert common.assert_target_not_memory("memory-adapter", "notify_seat.py") is None


def test_guard_constants_exposed(common):
    # dynamic_common.py re-exports these; keep them stable so tests &
    # tooling can reference canonical names rather than hardcoded strings.
    assert common.MEMORY_SEAT_NAME == "memory"
    assert "query_memory.py" in common.MEMORY_QUERY_POINTER
    assert "memory-query-protocol.md" in common.MEMORY_QUERY_POINTER


# ---------------------------------------------------------------------------
# Entrypoint integration — guard fires in main() BEFORE load_profile
# ---------------------------------------------------------------------------


def _invoke_main_with_argv(module, argv: list[str]) -> int:
    """Run module.main() with a patched sys.argv.

    We deliberately pass a bogus --profile path. If the guard fires first,
    load_profile is never called and the test passes. If it doesn't, we'd
    get a FileNotFoundError or similar, which would fail the test.
    """
    saved = sys.argv
    sys.argv = argv
    try:
        with pytest.raises(SystemExit) as excinfo:
            module.main()
        return excinfo.value.code
    finally:
        sys.argv = saved


@pytest.mark.parametrize(
    "module_fixture,argv",
    [
        (
            "dispatch_legacy",
            [
                "dispatch_task.py",
                "--profile", "/nonexistent/profile.toml",
                "--target", "memory",
                "--task-id", "t9-test-1",
                "--title", "should-be-blocked",
                "--objective", "body",
                "--test-policy", "UPDATE",
            ],
        ),
        (
            "dispatch_dynamic",
            [
                "dispatch_task_dynamic.py",
                "--profile", "/nonexistent/profile.toml",
                "--target", "memory",
                "--task-id", "t9-test-2",
                "--title", "should-be-blocked",
                "--objective", "body",
                "--test-policy", "UPDATE",
            ],
        ),
    ],
    ids=[
        "legacy.dispatch",
        "dynamic.dispatch",
    ],
)
def test_entrypoints_block_memory_target_before_profile_load(
    request, module_fixture, argv, capsys
):
    module = request.getfixturevalue(module_fixture)
    rc = _invoke_main_with_argv(module, argv)
    assert rc == 2
    err = capsys.readouterr().err
    assert "does not support --target memory" in err
    # Bogus profile path must NOT have been opened — if the guard fired
    # late, we would see a FileNotFoundError or IOError message instead.
    assert "/nonexistent/profile.toml" not in err or "does not support" in err


def test_dynamic_common_reexports_guard(dispatch_dynamic):
    # dispatch_task_dynamic.py imports assert_target_not_memory from
    # dynamic_common; make sure the re-export path is live.
    assert callable(dispatch_dynamic.assert_target_not_memory)
    assert dispatch_dynamic.assert_target_not_memory("planner", "x") is None


# ---------------------------------------------------------------------------
# T22 fold-in: notify_seat.py → memory now allowed (T7 compliance)
# ---------------------------------------------------------------------------


def test_notify_seat_to_memory_is_allowed_after_T22(common):
    # notify_seat.py may now target memory — T7 memory-query-protocol
    # Missing-Key Escalation requires memory to receive notifications.
    # The guard is a no-op for this caller.
    assert common.assert_target_not_memory("memory", "notify_seat.py") is None


def test_dispatch_task_to_memory_still_blocked(common, capsys):
    # dispatch_task.py (and all its variants) remain blocked from targeting
    # memory — memory doesn't read TODO.md so dispatching tasks to it is useless.
    with pytest.raises(SystemExit) as excinfo:
        common.assert_target_not_memory("memory", "dispatch_task.py")
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "does not support --target memory" in err
    assert "dispatch_task.py" in err
