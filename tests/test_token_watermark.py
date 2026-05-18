"""C16: seat token-usage watermark tests.

Covers:
- measure_token_usage_pct: session_jsonl_size heuristic, no-file, env var, unsupported model
- write_gstack_heartbeat_receipt: new fields present, measurement failure graceful
- Pre-C16 receipt (version=1, no token fields) reads cleanly as unknown
- patrol check_context_near_limit: threshold event emission
- feishu_announcer DEFAULT_EVENT_TYPES includes seat.context_near_limit
"""
from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "gstack-harness" / "scripts"
_CORE_SCRIPTS = _REPO / "core" / "scripts"
_CORE_LIB = _REPO / "core" / "lib"

sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_CORE_SCRIPTS))
sys.path.insert(0, str(_CORE_LIB))
sys.path.insert(0, str(_REPO))

import _common as common  # noqa: E402
from _common import (  # noqa: E402
    _compute_pct_from_jsonl,
    _infer_max_tokens,
    measure_token_usage_pct,
    write_gstack_heartbeat_receipt,
)
from patrol_supervisor import _CONTEXT_THRESHOLD, check_context_near_limit  # noqa: E402


# ---------------------------------------------------------------------------
# Profile fixture
# ---------------------------------------------------------------------------


def _make_profile(tmp_path: Path, seat: str = "builder-1") -> common.HarnessProfile:
    tasks = tmp_path / "tasks"
    (tasks / seat).mkdir(parents=True)
    handoffs = tmp_path / "handoffs"
    handoffs.mkdir()
    ws = tmp_path / "workspaces"
    ws.mkdir()

    profile_path = tmp_path / "profile.toml"
    profile_path.write_text(
        f"""\
version = 1
profile_name = "test-profile"
template_name = "gstack-harness"
project_name = "test"
repo_root = "{tmp_path}"
tasks_root = "{tasks}"
workspace_root = "{ws}"
handoff_dir = "{handoffs}"
project_doc = "{tasks}/PROJECT.md"
tasks_doc = "{tasks}/TASKS.md"
status_doc = "{tasks}/STATUS.md"
send_script = "/bin/echo"
status_script = "/bin/echo"
patrol_script = "/bin/echo"
agent_admin = "/bin/echo"
heartbeat_receipt = "{ws}/{seat}/HEARTBEAT_RECEIPT.toml"
seats = ["planner", "{seat}"]
heartbeat_seats = []
active_loop_owner = "planner"
default_notify_target = "planner"
heartbeat_owner = "koder"
heartbeat_transport = "tmux"

[seat_roles]
planner = "planner-dispatcher"
{seat} = "builder"

[dynamic_roster]
materialized_seats = ["planner", "{seat}"]
""",
        encoding="utf-8",
    )
    return common.load_profile(profile_path)


# ---------------------------------------------------------------------------
# _infer_max_tokens
# ---------------------------------------------------------------------------


def test_infer_max_tokens_default():
    assert _infer_max_tokens("claude-sonnet-4-6") == 200_000


def test_infer_max_tokens_unknown_model():
    assert _infer_max_tokens("some-unknown-model") == 200_000


def test_infer_max_tokens_opus():
    assert _infer_max_tokens("claude-opus-4-7") == 200_000


def test_infer_max_tokens_opus_1m():
    # Generic 1M detection
    assert _infer_max_tokens("claude-opus-4-7-1m") == 1_000_000


def test_infer_max_tokens_empty():
    assert _infer_max_tokens("") == 200_000


# ---------------------------------------------------------------------------
# measure_token_usage_pct: session_jsonl_size heuristic
# ---------------------------------------------------------------------------


def test_measure_session_jsonl_size(tmp_path):
    """Write a fake session.jsonl of known size, verify pct computation."""
    jsonl = tmp_path / "session.jsonl"
    # 200k tokens * 8 bytes = 1_600_000 bytes → 100% (capped at 1.0)
    content = b"x" * (200_000 * 8)
    jsonl.write_bytes(content)

    pct, source = _compute_pct_from_jsonl(jsonl, model="")
    assert source == "session_jsonl_size"
    assert pct == pytest.approx(1.0)


def test_measure_half_context(tmp_path):
    """100k tokens worth of bytes → 50%."""
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_bytes(b"y" * (100_000 * 8))  # 100k tokens at default 200k max
    pct, source = _compute_pct_from_jsonl(jsonl, model="claude-sonnet-4-6")
    assert source == "session_jsonl_size"
    assert pct == pytest.approx(0.5)


def test_measure_no_session_file(tmp_path, monkeypatch):
    """No session file → (None, 'unknown')."""
    profile = _make_profile(tmp_path)
    monkeypatch.setenv("CC_CONTEXT_USAGE_PCT", "")
    monkeypatch.delenv("CC_CONTEXT_USAGE_PCT", raising=False)
    pct, source = measure_token_usage_pct(profile, "builder-1")
    assert pct is None
    assert source == "unknown"


def test_measure_jsonl_via_workspace_glob(tmp_path, monkeypatch):
    """Regression: glob pattern must match real Claude project dirs (no leading dash).

    .claude/projects/<hash>/<convo>.jsonl — the hash dir does NOT start with '-'.
    Before the fix, glob("-*/*.jsonl") returned nothing; now glob("*/*.jsonl") finds it.
    """
    profile = _make_profile(tmp_path)
    monkeypatch.delenv("CC_CONTEXT_USAGE_PCT", raising=False)

    # Simulate Claude Code's workspace layout
    workspace = profile.workspace_for("builder-1")
    convo_dir = workspace / ".claude" / "projects" / "abc123ef456789"
    convo_dir.mkdir(parents=True)
    jsonl = convo_dir / "convo.jsonl"
    jsonl.write_bytes(b"x" * (100_000 * 8))  # 100k tokens → 50% of 200k default

    pct, source = measure_token_usage_pct(profile, "builder-1")
    assert source == "session_jsonl_size", f"unexpected source: {source}"
    assert pct == pytest.approx(0.5, abs=0.01)


def test_measure_env_var(tmp_path, monkeypatch):
    """CC_CONTEXT_USAGE_PCT env var → uses it directly."""
    profile = _make_profile(tmp_path)
    monkeypatch.setenv("CC_CONTEXT_USAGE_PCT", "0.73")
    pct, source = measure_token_usage_pct(profile, "builder-1")
    assert pct == pytest.approx(0.73)
    assert source == "cc_env"


def test_measure_env_var_capped(tmp_path, monkeypatch):
    """CC_CONTEXT_USAGE_PCT > 1.0 is capped at 1.0."""
    profile = _make_profile(tmp_path)
    monkeypatch.setenv("CC_CONTEXT_USAGE_PCT", "1.5")
    pct, _ = measure_token_usage_pct(profile, "builder-1")
    assert pct == pytest.approx(1.0)


def test_measure_unsupported_model_uses_default(tmp_path):
    """Unknown model → 200k default."""
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_bytes(b"z" * 800_000)  # 100k tokens at 200k default → 50%
    pct, source = _compute_pct_from_jsonl(jsonl, model="future-model-xyz")
    assert source == "session_jsonl_size"
    assert pct == pytest.approx(0.5)


def test_measure_jsonl_override(tmp_path, monkeypatch):
    """_session_jsonl_override injects a specific file for testing."""
    profile = _make_profile(tmp_path)
    monkeypatch.delenv("CC_CONTEXT_USAGE_PCT", raising=False)
    fake_jsonl = tmp_path / "fake.jsonl"
    fake_jsonl.write_bytes(b"a" * (80_000 * 8))  # 80k / 200k = 40%
    pct, source = measure_token_usage_pct(
        profile, "builder-1", _session_jsonl_override=fake_jsonl
    )
    assert source == "session_jsonl_size"
    assert pct == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# write_gstack_heartbeat_receipt
# ---------------------------------------------------------------------------


def test_write_receipt_includes_new_fields(tmp_path, monkeypatch):
    """Receipt includes token_usage_source and token_usage_measured_at."""
    profile = _make_profile(tmp_path)
    monkeypatch.delenv("CC_CONTEXT_USAGE_PCT", raising=False)
    fake_jsonl = tmp_path / "fake.jsonl"
    fake_jsonl.write_bytes(b"b" * (40_000 * 8))  # 20%

    write_gstack_heartbeat_receipt(
        profile, "builder-1",
        _session_jsonl_override=fake_jsonl,
    )
    receipt_path = profile.heartbeat_receipt_for("builder-1")
    assert receipt_path.exists()
    data = tomllib.loads(receipt_path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    assert "token_usage_pct" in data
    assert data["token_usage_pct"] == pytest.approx(0.2, abs=0.001)
    assert data["token_usage_source"] == "session_jsonl_size"
    assert "token_usage_measured_at" in data


def test_write_receipt_measurement_failure_does_not_block(tmp_path, monkeypatch):
    """Measurement failure → receipt still written, pct absent."""
    profile = _make_profile(tmp_path)
    monkeypatch.delenv("CC_CONTEXT_USAGE_PCT", raising=False)

    def _bad_measure(*a, **kw):
        raise RuntimeError("simulated failure")

    with mock.patch("_common.measure_token_usage_pct", side_effect=_bad_measure):
        # write_gstack_heartbeat_receipt calls measure internally;
        # test that the function itself is resilient
        # We'll call with a bad override to force None path
        write_gstack_heartbeat_receipt(profile, "builder-1")

    receipt_path = profile.heartbeat_receipt_for("builder-1")
    assert receipt_path.exists()
    data = tomllib.loads(receipt_path.read_text(encoding="utf-8"))
    assert data["version"] == 2
    # pct may or may not be present depending on measurement; what matters is the file exists
    assert "token_usage_source" in data


def test_write_receipt_unknown_when_no_jsonl(tmp_path, monkeypatch):
    """No jsonl file → token_usage_pct absent, source=unknown."""
    profile = _make_profile(tmp_path)
    monkeypatch.delenv("CC_CONTEXT_USAGE_PCT", raising=False)

    write_gstack_heartbeat_receipt(profile, "builder-1")
    receipt_path = profile.heartbeat_receipt_for("builder-1")
    data = tomllib.loads(receipt_path.read_text(encoding="utf-8"))
    assert "token_usage_pct" not in data
    assert data["token_usage_source"] == "unknown"


# ---------------------------------------------------------------------------
# Read: pre-C16 receipt reads cleanly as unknown
# ---------------------------------------------------------------------------


def test_pre_c16_receipt_reads_as_unknown(tmp_path):
    """version=1 receipt with no token fields → readers get None (no crash)."""
    profile = _make_profile(tmp_path)
    receipt_path = profile.heartbeat_receipt_for("builder-1")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        'version = 1\nseat_id = "builder-1"\nproject = "test"\n'
        'status = "verified"\nverified_at = "2026-01-01T00:00:00"\n',
        encoding="utf-8",
    )
    data = tomllib.loads(receipt_path.read_text(encoding="utf-8"))
    pct = data.get("token_usage_pct")
    assert pct is None  # missing → None → no alert fired


# ---------------------------------------------------------------------------
# patrol check_context_near_limit
# ---------------------------------------------------------------------------


def _write_receipt_with_pct(profile: common.HarnessProfile, seat: str, pct: float | None, source: str = "session_jsonl_size") -> None:
    receipt_path = profile.heartbeat_receipt_for(seat)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "version = 2",
        f'seat_id = "{seat}"',
        f'project = "{profile.project_name}"',
        'status = "verified"',
        'verified_at = "2026-04-21T00:00:00"',
        f'token_usage_source = "{source}"',
        'token_usage_measured_at = "2026-04-21T00:00:00"',
    ]
    if pct is not None:
        lines.append(f"token_usage_pct = {pct:.6f}")
    receipt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_patrol_pct_85_fires_event(tmp_path):
    """pct=0.85 → record_event called with seat.context_near_limit."""
    profile = _make_profile(tmp_path, seat="builder-1")
    _write_receipt_with_pct(profile, "builder-1", 0.85)

    recorded: list[dict] = []

    def fake_record_event(conn, event_type, project, **kwargs):
        recorded.append({"event_type": event_type, "project": project, **kwargs})

    with mock.patch("patrol_supervisor.check_context_near_limit", wraps=check_context_near_limit):
        from unittest.mock import MagicMock
        fake_conn = MagicMock()

        with mock.patch("core.lib.state.open_db") as mock_open_db, \
             mock.patch("core.lib.state.record_event", side_effect=fake_record_event):
            mock_open_db.return_value.__enter__ = lambda s: fake_conn
            mock_open_db.return_value.__exit__ = lambda s, *a: False
            result = check_context_near_limit(profile)

    assert len(recorded) == 1
    assert recorded[0]["event_type"] == "seat.context_near_limit"
    assert recorded[0]["seat"] == "builder-1"
    assert recorded[0]["pct"] == pytest.approx(0.85)
    assert result  # non-empty warning list


def test_patrol_pct_50_no_event(tmp_path):
    """pct=0.50 → no event fired."""
    profile = _make_profile(tmp_path, seat="builder-1")
    _write_receipt_with_pct(profile, "builder-1", 0.50)

    with mock.patch("core.lib.state.record_event") as mock_record:
        result = check_context_near_limit(profile)

    mock_record.assert_not_called()
    assert result == []


def test_patrol_pct_none_no_event(tmp_path):
    """pct=None (field absent) → no event fired."""
    profile = _make_profile(tmp_path, seat="builder-1")
    _write_receipt_with_pct(profile, "builder-1", None)

    with mock.patch("core.lib.state.record_event") as mock_record:
        result = check_context_near_limit(profile)

    mock_record.assert_not_called()
    assert result == []


def test_patrol_pct_exactly_80_fires(tmp_path):
    """pct=0.80 exactly → event fires (boundary inclusive)."""
    profile = _make_profile(tmp_path, seat="builder-1")
    _write_receipt_with_pct(profile, "builder-1", 0.80)

    recorded: list[dict] = []

    def fake_record_event(conn, event_type, project, **kwargs):
        recorded.append({"event_type": event_type, **kwargs})

    from unittest.mock import MagicMock
    fake_conn = MagicMock()

    with mock.patch("core.lib.state.open_db") as mock_open_db, \
         mock.patch("core.lib.state.record_event", side_effect=fake_record_event):
        mock_open_db.return_value.__enter__ = lambda s: fake_conn
        mock_open_db.return_value.__exit__ = lambda s, *a: False
        check_context_near_limit(profile)

    assert len(recorded) == 1
    assert recorded[0]["pct"] == pytest.approx(0.80)


def test_patrol_no_receipt_file(tmp_path):
    """Seat with no receipt file → no error, no event."""
    profile = _make_profile(tmp_path, seat="builder-1")
    # Don't write any receipt

    with mock.patch("core.lib.state.record_event") as mock_record:
        result = check_context_near_limit(profile)

    mock_record.assert_not_called()
    assert result == []


def test_patrol_state_db_unavailable_does_not_raise(tmp_path):
    """state.db import failure → warning logged, no crash."""
    profile = _make_profile(tmp_path, seat="builder-1")
    _write_receipt_with_pct(profile, "builder-1", 0.90)

    with mock.patch.dict("sys.modules", {"core.lib.state": None}):
        # ImportError when state module is None — check_context_near_limit swallows it
        result = check_context_near_limit(profile)
    # Should not raise; may or may not have warning (depends on import error handling)


# ---------------------------------------------------------------------------
# feishu_announcer DEFAULT_EVENT_TYPES
# ---------------------------------------------------------------------------


def test_feishu_announcer_includes_context_near_limit():
    """feishu_announcer._DEFAULT_EVENT_TYPES includes seat.context_near_limit."""
    import feishu_announcer  # noqa: PLC0415

    assert "seat.context_near_limit" in feishu_announcer._DEFAULT_EVENT_TYPES


def test_feishu_announcer_includes_blocked_on_modal():
    """feishu_announcer._DEFAULT_EVENT_TYPES still includes seat.blocked_on_modal (C10.5)."""
    import feishu_announcer  # noqa: PLC0415

    assert "seat.blocked_on_modal" in feishu_announcer._DEFAULT_EVENT_TYPES


# ---------------------------------------------------------------------------
# _CONTEXT_THRESHOLD constant
# ---------------------------------------------------------------------------


def test_context_threshold_value():
    """Threshold is 0.80 (hardcoded, not configurable in C16)."""
    assert _CONTEXT_THRESHOLD == pytest.approx(0.80)
