"""Regression tests for Batch B hardening items.

Covers:

- **M5** — `_feishu._reject_invalid_feishu_group_id` discards malformed
  Feishu group ids (typo'd prefix, wrong shape) with a stderr warning
  instead of letting them flow into `lark-cli` and surface as a cryptic
  404. Env-var override + openclaw.json + sessions.json + workspace
  contract paths all run the same validator.
- **M17** — heartbeat receipts older than `RECEIPT_VALID_FOR_SECONDS`
  are no longer treated as "verified" even when their fingerprint
  still matches. `CLAWSEAT_HEARTBEAT_RECEIPT_TTL_SECONDS` overrides the
  window for sandbox runs.
- **M20** — `check-engineer-status.sh` no longer uses `echo "$RAW"`
  which can interpret backslash escapes on some shells. Guard against
  re-introduction.
- **L8** — `_bridge_adapters._get_tmux_adapter_module` now double-checks
  under a `threading.Lock`; a multi-threaded bridge host cannot load
  two different module objects.
- **L10** — `_bridge_binding._assert_parent_is_not_symlink` rejects any
  symlinked component on the path to `~/.agents/projects/<proj>/`, so
  a symlink-race attack cannot trick ClawSeat into writing BRIDGE.toml
  outside the intended tree.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_SCRIPTS_HARNESS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_SCRIPTS_ADMIN = _REPO / "core" / "scripts"
_SHELLS_OCLAW = _REPO / "shells" / "openclaw-plugin"
for _p in (_SCRIPTS_HARNESS, _SCRIPTS_ADMIN, _SHELLS_OCLAW):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ── M5: Feishu group id validation ──────────────────────────────────


def test_valid_group_id_accepted() -> None:
    from _feishu import is_valid_feishu_group_id

    assert is_valid_feishu_group_id("<FEISHU_GROUP_ID>")
    assert is_valid_feishu_group_id("oc_" + "x" * 40)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "*",
        "anything",              # missing oc_ prefix
        "OC_abcdef1234",         # wrong case
        "oc_",                   # prefix only, no body
        "oc_abc!def1234",        # disallowed punctuation
        "og_abcdef1234",         # typo'd prefix
        "oc abc",                # whitespace
    ],
)
def test_invalid_group_ids_rejected(bad: str) -> None:
    from _feishu import is_valid_feishu_group_id

    assert not is_valid_feishu_group_id(bad)


@pytest.mark.parametrize(
    "ok",
    [
        "<FEISHU_GROUP_ID>",     # uppercase + underscores, seen in repo fixtures
        "<FEISHU_GROUP_ID>",       # same shape, shorter
        "<FEISHU_GROUP_ID>",
        "oc_zzz",                # short suffix — real ids can be terse in tests
        "<FEISHU_GROUP_ID>",           # hyphen
    ],
)
def test_realistic_group_ids_accepted(ok: str) -> None:
    """Regression — the validator must not reject real-world shaped
    group ids. Seen in tests/test_real_user_home_resolution.py and
    other Feishu-id fixtures across the suite."""
    from _feishu import is_valid_feishu_group_id

    assert is_valid_feishu_group_id(ok)


def test_collect_feishu_group_ids_from_config_filters_invalid(capsys) -> None:
    from _feishu import collect_feishu_group_ids_from_config

    config = {
        "channels": {
            "feishu": {
                "groups": {
                    "<FEISHU_GROUP_ID>": {},
                    "not-an-oc-id": {},
                    "*": {},
                },
            },
        },
    }
    found = collect_feishu_group_ids_from_config(config)
    assert found == ["<FEISHU_GROUP_ID>"]
    err = capsys.readouterr().err
    assert "INPUT" not in err  # M5 uses `warn:` not INPUT_REJECTED
    assert "not-an-oc-id" in err


def test_env_override_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    from _feishu import resolve_primary_feishu_group_id

    monkeypatch.setenv("CLAWSEAT_FEISHU_GROUP_ID", "<FEISHU_GROUP_ID>")
    # Downstream WORKSPACE_CONTRACT lookup may still match; the env
    # override should short-circuit on the well-formed id.
    result = resolve_primary_feishu_group_id(project="unit-test")
    assert result == "<FEISHU_GROUP_ID>"


def test_env_override_rejects_garbage(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from _feishu import resolve_primary_feishu_group_id

    monkeypatch.setenv("CLAWSEAT_FEISHU_GROUP_ID", "not-a-group-id")
    # The env override should be discarded; downstream lookup may yield
    # another value or None — we only care the invalid one doesn't
    # leak into the return.
    result = resolve_primary_feishu_group_id(project="unit-test")
    if result is not None:
        assert result != "not-a-group-id"
    assert "not-a-group-id" in capsys.readouterr().err


# ── M17: heartbeat receipt freshness ────────────────────────────────


def _make_handlers(tmp_path: Path):
    from agent_admin_heartbeat import HeartbeatHandlers, HeartbeatHooks

    # Minimal hooks — receipt_matches_manifest only touches a couple of
    # them; the rest are filled in with no-ops / lambdas so construction
    # doesn't fail.
    hooks = HeartbeatHooks(
        error_cls=RuntimeError,
        send_and_verify_sh=str(tmp_path / "send.sh"),
        q=lambda v: f'"{v}"',
        q_array=lambda xs: "[" + ", ".join(f'"{v}"' for v in xs) + "]",
        ensure_dir=lambda p: p.mkdir(parents=True, exist_ok=True),
        write_text=lambda p, c, **_: p.write_text(c),
        load_toml=lambda p: {},
        tmux_has_session=lambda s: False,
        find_active_loop_owner=lambda *a, **kw: None,
    )
    return HeartbeatHandlers(hooks)


def _fresh_receipt(now: datetime, fingerprint: str = "FP") -> dict:
    return {
        "status": "verified",
        "seat_id": "koder",
        "session": "proj-koder",
        "install_fingerprint": fingerprint,
        "manifest_fingerprint": fingerprint,
        "verified_at": now.isoformat(timespec="seconds"),
    }


def test_receipt_matches_manifest_accepts_recent(tmp_path: Path) -> None:
    handlers = _make_handlers(tmp_path)
    session = SimpleNamespace(engineer_id="koder", session="proj-koder", project="proj")
    manifest = {"seat_id": "koder", "project": "proj", "session": "proj-koder"}

    # Pin fingerprints so the match is determined by freshness alone.
    with patch.object(handlers, "install_fingerprint", return_value="FP"), \
         patch.object(handlers, "manifest_fingerprint", return_value="FP"):
        recent = _fresh_receipt(datetime.now() - timedelta(minutes=5))
        assert handlers.receipt_matches_manifest(recent, manifest, session)


def test_receipt_matches_manifest_rejects_stale(tmp_path: Path) -> None:
    handlers = _make_handlers(tmp_path)
    session = SimpleNamespace(engineer_id="koder", session="proj-koder", project="proj")
    manifest = {"seat_id": "koder", "project": "proj", "session": "proj-koder"}

    with patch.object(handlers, "install_fingerprint", return_value="FP"), \
         patch.object(handlers, "manifest_fingerprint", return_value="FP"):
        stale = _fresh_receipt(datetime.now() - timedelta(days=3))
        assert not handlers.receipt_matches_manifest(stale, manifest, session), (
            "3-day-old receipt must not be considered verified even when fingerprint matches"
        )


def test_receipt_ttl_respects_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handlers = _make_handlers(tmp_path)
    session = SimpleNamespace(engineer_id="koder", session="proj-koder", project="proj")
    manifest = {"seat_id": "koder", "project": "proj", "session": "proj-koder"}

    monkeypatch.setenv("CLAWSEAT_HEARTBEAT_RECEIPT_TTL_SECONDS", "60")
    with patch.object(handlers, "install_fingerprint", return_value="FP"), \
         patch.object(handlers, "manifest_fingerprint", return_value="FP"):
        two_min_old = _fresh_receipt(datetime.now() - timedelta(minutes=2))
        assert not handlers.receipt_matches_manifest(two_min_old, manifest, session)


def test_receipt_missing_timestamp_is_rejected(tmp_path: Path) -> None:
    handlers = _make_handlers(tmp_path)
    session = SimpleNamespace(engineer_id="koder", session="proj-koder", project="proj")
    manifest = {"seat_id": "koder", "project": "proj", "session": "proj-koder"}
    with patch.object(handlers, "install_fingerprint", return_value="FP"), \
         patch.object(handlers, "manifest_fingerprint", return_value="FP"):
        receipt = _fresh_receipt(datetime.now())
        receipt.pop("verified_at")
        assert not handlers.receipt_matches_manifest(receipt, manifest, session)


# ── M20: check-engineer-status.sh no longer uses echo "$RAW" ────────


def test_check_engineer_status_shell_no_longer_uses_echo_raw() -> None:
    path = _REPO / "core" / "shell-scripts" / "check-engineer-status.sh"
    source = path.read_text(encoding="utf-8")
    offending = [
        line
        for line in source.splitlines()
        if 'echo "$RAW"' in line
    ]
    assert not offending, (
        "check-engineer-status.sh should use `printf '%s\\n' \"$RAW\"` instead "
        "of `echo \"$RAW\"` — echo interprets backslash escapes on some shells "
        "and corrupts pane text (audit M20). Offending lines:\n  " + "\n  ".join(offending)
    )


def test_check_engineer_status_shell_parses() -> None:
    path = _REPO / "core" / "shell-scripts" / "check-engineer-status.sh"
    result = subprocess.run(
        ["bash", "-n", str(path)], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 0, f"shell syntax broke: {result.stderr}"


# ── L8: tmux-adapter lazy load lock ─────────────────────────────────


def test_bridge_adapters_uses_lock() -> None:
    from shells.openclaw_plugin import _bridge_adapters  # type: ignore[attr-defined]


def test_bridge_adapters_source_has_threading_lock() -> None:
    path = _REPO / "shells" / "openclaw-plugin" / "_bridge_adapters.py"
    source = path.read_text(encoding="utf-8")
    assert "import threading" in source
    assert "_TMUX_ADAPTER_LOCK" in source
    assert "with _TMUX_ADAPTER_LOCK" in source, (
        "_get_tmux_adapter_module must take _TMUX_ADAPTER_LOCK on the slow path"
    )


# ── L10: bridge binding symlink defense ─────────────────────────────


def test_bridge_binding_refuses_symlinked_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import _bridge_binding as bb

    # Point `_projects_root` at our tmp dir, then replace
    # `projects/demo` with a symlink to an attacker-controlled path.
    fake_root = tmp_path / "agents" / "projects"
    fake_root.mkdir(parents=True)
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    (fake_root / "demo").symlink_to(attacker)

    monkeypatch.setattr(bb, "_projects_root", lambda: fake_root)

    target = fake_root / "demo" / "BRIDGE.toml"
    with pytest.raises(RuntimeError, match="refusing to write through symlinked component"):
        bb._write_bridge_file(
            target,
            {
                "project": "demo",
                "group_id": "<FEISHU_GROUP_ID>",
                "account_id": "app",
                "session_key": "sess",
                "bound_at": "2026-04-20T00:00:00Z",
                "bound_by": "test",
            },
        )

    # BRIDGE.toml did not land on the attacker side.
    assert not (attacker / "BRIDGE.toml").exists()


def test_bridge_binding_allows_clean_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import _bridge_binding as bb

    fake_root = tmp_path / "agents" / "projects"
    fake_root.mkdir(parents=True)
    monkeypatch.setattr(bb, "_projects_root", lambda: fake_root)
    target = fake_root / "clean" / "BRIDGE.toml"
    bb._write_bridge_file(
        target,
        {
            "project": "clean",
            "group_id": "<FEISHU_GROUP_ID>",
            "account_id": "app",
            "session_key": "sess",
            "bound_at": "2026-04-20T00:00:00Z",
            "bound_by": "test",
        },
    )
    assert target.exists()
    assert "[bridge]" in target.read_text()


# ── L12: legacy transport fields stay behind compat helpers ─────────


def test_seat_resolver_profile_helpers_override_legacy_attrs(tmp_path: Path) -> None:
    from core.lib import seat_resolver as sr

    oc_home = tmp_path / ".openclaw"
    contract = oc_home / "workspace-frontstage" / "WORKSPACE_CONTRACT.toml"
    contract.parent.mkdir(parents=True)
    contract.write_text(
        'seat_id = "koder"\n'
        'project = "demo"\n'
        'feishu_group_id = "<FEISHU_GROUP_ID>"\n',
        encoding="utf-8",
    )

    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    profile = SimpleNamespace(
        seats=["koder", "planner"],
        runtime_seats=["koder", "planner"],  # stale legacy attr must not win
        heartbeat_owner="planner",
        heartbeat_transport="tmux",
        project_name="demo",
        handoff_dir=handoff_dir,
        tmux_runtime_seats=lambda: ["planner"],
        frontstage_target_seat=lambda: "koder",
        frontstage_transport_kind=lambda: "openclaw",
    )

    with patch.object(sr, "_openclaw_home_resolved", return_value=oc_home):
        result = sr.resolve_seat_from_profile("koder", profile)

    assert result.kind == "openclaw"
    assert result.group_id == "<FEISHU_GROUP_ID>"
    assert result.agent_name == "frontstage"


def test_make_local_override_marks_legacy_transport_fields_as_compat(tmp_path: Path) -> None:
    import _common as common

    profile = SimpleNamespace(
        materialized_seats=["koder", "planner"],
        seats=["koder", "planner"],
        runtime_seats=["planner"],
        bootstrap_seats=["koder"],
        default_start_seats=["koder", "planner"],
        heartbeat_transport="openclaw",
        seat_overrides={},
        compat_materialized_seats=lambda: ["koder", "planner"],
        tmux_runtime_seats=lambda: ["planner"],
        frontstage_transport_kind=lambda: "openclaw",
    )

    override = common.make_local_override(profile, project_name="demo", repo_root=tmp_path)
    text = override.read_text(encoding="utf-8")

    assert "# Local override / legacy harness compatibility fields." in text
    assert "# Layered v2 profiles do not store these keys directly." in text
    assert 'materialized_seats = ["koder", "planner"]' in text
    assert 'runtime_seats = ["planner"]' in text
    assert 'heartbeat_transport = "openclaw"' in text
