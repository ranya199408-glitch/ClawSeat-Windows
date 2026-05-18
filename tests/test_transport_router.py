"""Regression tests for the canonical transport router and the shared
`build_notify_payload` helper (audit items H1 + H2).

H1 — `core/transport/transport_router.py` is the single entry point for
dispatch/notify/complete. The old `core/transport.py` (DefaultTransportAdapter)
was deleted; these tests pin the router's routing semantics so any
re-introduction of a second transport path is caught early.

H2 — `build_notify_payload` is shared by both `notify_seat.py` (legacy) and
`notify_seat_dynamic.py` (dynamic). Previously each defined its own
`build_payload` and the dynamic one silently added a `[project_name]` prefix.
These tests lock the two call modes to the same helper.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


# ── H1: transport_router routing helpers ─────────────────────────────

def _load_router(repo_root: Path):
    router_path = repo_root / "core" / "transport" / "transport_router.py"
    spec = importlib.util.spec_from_file_location("transport_router", router_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_router_detects_dynamic_profile(repo_root: Path, harness_profile: Path) -> None:
    router = _load_router(repo_root)
    assert router.is_dynamic_profile(harness_profile) is True


def test_router_treats_missing_profile_as_non_dynamic(repo_root: Path, tmp_path: Path) -> None:
    router = _load_router(repo_root)
    assert router.is_dynamic_profile(tmp_path / "does-not-exist.toml") is False


def test_router_treats_non_dynamic_profile_as_legacy(repo_root: Path, tmp_path: Path) -> None:
    router = _load_router(repo_root)
    profile = tmp_path / "legacy.toml"
    profile.write_text('project_name = "legacy"\n', encoding="utf-8")
    assert router.is_dynamic_profile(profile) is False


def test_router_command_scripts_cover_all_operations(repo_root: Path) -> None:
    router = _load_router(repo_root)
    # Every command must have BOTH a dynamic and legacy implementation.
    for command, scripts in router.COMMAND_SCRIPTS.items():
        assert set(scripts.keys()) == {"dynamic", "legacy"}, command
        for variant, script in scripts.items():
            assert script.exists(), f"{command}/{variant} missing at {script}"


def test_router_resolve_profile_prefers_dynamic_sibling(
    repo_root: Path, tmp_path: Path, harness_profile: Path
) -> None:
    router = _load_router(repo_root)
    # Simulate the "legacy file exists but a *-dynamic.toml sibling also exists" case.
    legacy = tmp_path / "foo.toml"
    legacy.write_text('project_name = "foo"\n', encoding="utf-8")
    sibling = tmp_path / "foo-dynamic.toml"
    sibling.write_text(harness_profile.read_text(encoding="utf-8"), encoding="utf-8")
    selected, is_dynamic = router.resolve_profile(str(legacy), None)
    assert is_dynamic is True
    assert selected.resolve() == sibling.resolve()


def test_router_resolve_profile_returns_legacy_when_no_dynamic(
    repo_root: Path, tmp_path: Path
) -> None:
    router = _load_router(repo_root)
    legacy = tmp_path / "legacy-only.toml"
    legacy.write_text('project_name = "legacy-only"\n', encoding="utf-8")
    selected, is_dynamic = router.resolve_profile(str(legacy), None)
    assert is_dynamic is False
    assert selected == legacy


def test_router_strip_and_replace_flag_roundtrip(repo_root: Path) -> None:
    router = _load_router(repo_root)
    args = ["--source", "a", "--profile", "/tmp/p.toml", "--target", "b"]
    stripped, value = router.strip_flag_value(args, "--profile")
    assert value == "/tmp/p.toml"
    assert "--profile" not in stripped
    replaced = router.replace_flag_value(args, "--profile", "/new/p.toml")
    assert "/new/p.toml" in replaced
    assert "/tmp/p.toml" not in replaced


# ── H2: build_notify_payload shared helper ───────────────────────────

def _load_payload_helpers():
    """Import build_notify_payload from BOTH modules and return them.

    Both must resolve to the same callable (the gstack-harness
    `_task_io.build_notify_payload`); this is the anti-drift assertion.
    """
    from _common import build_notify_payload as legacy_entry
    from dynamic_common import build_notify_payload as dynamic_entry
    return legacy_entry, dynamic_entry


def test_payload_legacy_and_dynamic_share_source() -> None:
    """Anti-drift guard: both notify_seat entrypoints must resolve
    `build_notify_payload` to the *same underlying function definition*
    — the one in gstack-harness `_task_io.py`. `dynamic_common.py`
    deliberately loads a private copy of `_common.py` via importlib
    (so BASE_COMMON can be namespaced), which means the function
    objects will NOT be identity-equal across imports. Instead we
    check that they resolve to the same qualname and live in the
    same source file, and produce identical output for identical
    inputs — the behavioural guarantee that matters for drift."""
    import inspect

    legacy_entry, dynamic_entry = _load_payload_helpers()
    # Source-file identity: both must come from the same physical
    # `_task_io.py` (not two forked copies).
    assert inspect.getsourcefile(legacy_entry) == inspect.getsourcefile(dynamic_entry), (
        f"legacy entry from {inspect.getsourcefile(legacy_entry)!r} but dynamic "
        f"entry from {inspect.getsourcefile(dynamic_entry)!r} — the two paths "
        "are forking."
    )
    assert legacy_entry.__qualname__ == dynamic_entry.__qualname__
    # Behavioural identity: same inputs → same output on both paths.
    kwargs = dict(source="a", target="b", message="hi", kind="notice", task_id="T", reply_to="a")
    assert legacy_entry(**kwargs) == dynamic_entry(**kwargs)


def test_payload_legacy_format_has_no_project_prefix() -> None:
    legacy_entry, _ = _load_payload_helpers()
    payload = legacy_entry(
        source="koder",
        target="planner",
        message="ping",
        kind="notice",
        task_id="T1",
        reply_to="koder",
    )
    assert payload.startswith("T1 notice from koder to planner:")
    assert not payload.startswith("[")


def test_payload_dynamic_format_has_project_prefix() -> None:
    _, dynamic_entry = _load_payload_helpers()
    payload = dynamic_entry(
        source="koder",
        target="planner",
        message="ping",
        kind="notice",
        task_id="T1",
        reply_to="koder",
        project_name="demo",
    )
    assert payload.startswith("[demo] T1 notice from koder to planner:")


def test_payload_strips_message_whitespace() -> None:
    legacy_entry, _ = _load_payload_helpers()
    payload = legacy_entry(source="a", target="b", message="  hi  ")
    assert payload.endswith(": hi")


@pytest.mark.parametrize(
    "task_id,reply_to,expect_reply_suffix",
    [
        (None, None, False),
        ("T9", None, False),
        (None, "koder", True),
        ("T9", "koder", True),
    ],
)
def test_payload_reply_to_suffix_respects_flag(
    task_id: str | None, reply_to: str | None, expect_reply_suffix: bool
) -> None:
    legacy_entry, _ = _load_payload_helpers()
    payload = legacy_entry(
        source="a",
        target="b",
        message="x",
        task_id=task_id,
        reply_to=reply_to,
    )
    assert ("Reply to" in payload) is expect_reply_suffix


# ── H2b: dispatch/complete shared helper drift guard ─────────────────
#
# `build_notify_payload` is not the only helper shared by the dynamic and
# legacy paths. `dispatch_task_dynamic.py` / `complete_handoff_dynamic.py`
# import a wider set of `_task_io` helpers (write_todo, write_delivery,
# build_completion_message, append_task_to_queue, upsert_tasks_row,
# append_status_note, append_consumed_ack) through `dynamic_common.py`,
# which re-exports them from the same private-loaded `_common` as the
# legacy `from _common import ...` path.
#
# If anyone replaces a re-export with a dynamic-side reimplementation
# (or forks a helper into `dynamic_common.py`), dispatch/complete output
# silently diverges between the two transport paths. This test locks the
# source-file identity of every helper consumed by BOTH sides.

SHARED_TASK_IO_HELPERS = (
    "build_notify_message",
    "build_notify_payload",
    "build_completion_message",
    "write_todo",
    "write_delivery",
    "upsert_tasks_row",
    "append_status_note",
    "append_consumed_ack",
    "notify",
)


@pytest.mark.parametrize("helper_name", SHARED_TASK_IO_HELPERS)
def test_shared_task_io_helpers_do_not_fork(helper_name: str) -> None:
    """Source-file identity check for every helper imported by both the
    legacy (`_common`) and dynamic (`dynamic_common`) paths. A drift
    here means the two transport backends are no longer emitting the
    same TODO.md / DELIVERY.md / TASKS.md text — the symptom the audit
    was trying to prevent."""
    import inspect

    import _common as legacy_common  # harness scripts dir on sys.path
    from core.migration import dynamic_common

    legacy_fn = getattr(legacy_common, helper_name)
    dynamic_fn = getattr(dynamic_common, helper_name)
    legacy_src = inspect.getsourcefile(legacy_fn)
    dynamic_src = inspect.getsourcefile(dynamic_fn)
    assert legacy_src == dynamic_src, (
        f"{helper_name} has forked: legacy={legacy_src!r} "
        f"dynamic={dynamic_src!r}. Re-export from BASE_COMMON in "
        f"core/migration/dynamic_common.py instead of defining a new copy."
    )
    assert legacy_fn.__qualname__ == dynamic_fn.__qualname__


# ── H1: dead core/transport.py must stay gone ────────────────────────

def test_old_transport_module_is_deleted(repo_root: Path) -> None:
    """Regression guard — the old `core/transport.py` (with
    DefaultTransportAdapter) was deleted as part of H1. If it ever
    reappears without going through transport_router, routing can
    silently drift to a second code path."""
    assert not (repo_root / "core" / "transport.py").exists(), (
        "core/transport.py was removed in the H1 audit fix. Re-introducing "
        "it risks bypassing transport_router. Extend the Protocol there "
        "or add a subclass of the router instead."
    )
