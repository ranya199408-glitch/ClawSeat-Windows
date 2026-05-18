"""Tests for check_feishu_auth() — user-token longevity fix.

Covers:
  1. needs_refresh → ok+warning (lark-cli auto-refreshes, not a fail)
  2. keepalive ping fires when grantedAt > REFRESH_KEEPALIVE_DAYS
  3. expired (refresh_token past 7d) still returns status=expired
  4. keepalive + expired: ping fails, status stays expired (no false ok)
"""
from __future__ import annotations

import datetime
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import _feishu


# ── Helpers ──────────────────────────────────────────────────────────

def _fake_completed(stdout: str = "", stderr: str = "", rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def _auth_json(
    *,
    token_status: str = "valid",
    granted_at: str | None = None,
    refresh_expires_at: str | None = None,
    user_open_id: str = "<FEISHU_OPEN_ID>",
    user_name: str = "Tester",
    identity: str = "user",
) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    if granted_at is None:
        granted_at = now.isoformat()
    if refresh_expires_at is None:
        refresh_expires_at = (now + datetime.timedelta(days=7)).isoformat()
    return json.dumps(
        {
            "identity": identity,
            "tokenStatus": token_status,
            "userName": user_name,
            "userOpenId": user_open_id,
            "grantedAt": granted_at,
            "refreshExpiresAt": refresh_expires_at,
        }
    )


@pytest.fixture(autouse=True)
def fake_lark_cli_in_path(monkeypatch):
    """Pretend lark-cli is installed (shutil.which returns a path)."""
    monkeypatch.setattr(_feishu.shutil, "which", lambda _: "/fake/lark-cli")


# ── 1. needs_refresh → ok + warning ──────────────────────────────────

def test_needs_refresh_returns_ok_with_warning(monkeypatch):
    """access_token expired but refresh_token still valid → must NOT fail."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # Both the initial and (possibly) post-keepalive read return needs_refresh
        return _fake_completed(stdout=_auth_json(token_status="needs_refresh"))

    monkeypatch.setattr(_feishu, "run_command_with_env", fake_run)

    result = _feishu.check_feishu_auth()
    assert result["status"] == "ok", f"needs_refresh must be ok, got {result}"
    assert result.get("warning") == "needs_refresh"


# ── 2. keepalive ping fires on stale grantedAt ───────────────────────

def test_keepalive_triggers_ping_when_granted_stale(monkeypatch):
    """grantedAt older than REFRESH_KEEPALIVE_DAYS + keepalive=True → user_info call."""
    stale = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=_feishu.REFRESH_KEEPALIVE_DAYS + 1)
    ).isoformat()
    fresh_after_refresh = datetime.datetime.now(datetime.timezone.utc).isoformat()

    call_log: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        call_log.append(list(cmd))
        # First auth status → stale grantedAt
        # user_info ping → success
        # Second auth status (post-refresh) → fresh grantedAt, valid
        if cmd[1:3] == ["auth", "status"]:
            if len([c for c in call_log if c[1:3] == ["auth", "status"]]) == 1:
                return _fake_completed(
                    stdout=_auth_json(token_status="valid", granted_at=stale)
                )
            return _fake_completed(
                stdout=_auth_json(token_status="valid", granted_at=fresh_after_refresh)
            )
        if cmd[1:4] == ["api", "GET", "/open-apis/authen/v1/user_info"]:
            return _fake_completed(stdout='{"user_id":"x"}')
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(_feishu, "run_command_with_env", fake_run)
    result = _feishu.check_feishu_auth(keepalive=True)

    assert result["status"] == "ok"
    # Must have issued the keepalive ping
    assert any(
        c[1:4] == ["api", "GET", "/open-apis/authen/v1/user_info"] for c in call_log
    ), f"keepalive ping not fired; calls were: {call_log}"


def test_keepalive_skipped_when_granted_recent(monkeypatch):
    """grantedAt fresh → no ping (don't waste an API call)."""
    call_log: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        call_log.append(list(cmd))
        return _fake_completed(stdout=_auth_json(token_status="valid"))

    monkeypatch.setattr(_feishu, "run_command_with_env", fake_run)
    result = _feishu.check_feishu_auth(keepalive=True)

    assert result["status"] == "ok"
    assert not any(c[1:2] == ["api"] for c in call_log), (
        f"no keepalive should fire for fresh token; calls: {call_log}"
    )


def test_keepalive_disabled_by_default(monkeypatch):
    """keepalive=False (default) never calls user_info, even with stale grantedAt."""
    stale = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=_feishu.REFRESH_KEEPALIVE_DAYS + 1)
    ).isoformat()
    call_log: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        call_log.append(list(cmd))
        return _fake_completed(stdout=_auth_json(token_status="valid", granted_at=stale))

    monkeypatch.setattr(_feishu, "run_command_with_env", fake_run)
    _feishu.check_feishu_auth()  # default keepalive=False

    assert not any(c[1:2] == ["api"] for c in call_log), (
        f"keepalive should NOT fire when keepalive=False; calls: {call_log}"
    )


# ── 3. expired (refresh_token dead) still fails loudly ───────────────

def test_expired_still_fails(monkeypatch):
    """tokenStatus=expired (>7d idle) → status=expired, fix requires login."""
    monkeypatch.setattr(
        _feishu,
        "run_command_with_env",
        lambda cmd, **kw: _fake_completed(stdout=_auth_json(token_status="expired")),
    )
    result = _feishu.check_feishu_auth()
    assert result["status"] == "expired"
    assert "lark-cli auth login" in result.get("fix", "")


# ── 4. keepalive cannot rescue expired refresh_token ─────────────────

def test_keepalive_with_expired_token_stays_expired(monkeypatch):
    """keepalive=True + tokenStatus=expired: ping fails, status must remain expired.

    Guards against a regression where a failed keepalive ping might leave
    the caller thinking the token is ok.
    """
    stale = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(days=_feishu.REFRESH_KEEPALIVE_DAYS + 2)
    ).isoformat()
    call_log: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        call_log.append(list(cmd))
        if cmd[1:3] == ["auth", "status"]:
            return _fake_completed(
                stdout=_auth_json(token_status="expired", granted_at=stale)
            )
        if cmd[1:4] == ["api", "GET", "/open-apis/authen/v1/user_info"]:
            # Refresh token is dead → ping fails
            return _fake_completed(stderr="token expired", rc=1)
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(_feishu, "run_command_with_env", fake_run)
    result = _feishu.check_feishu_auth(keepalive=True)
    assert result["status"] == "expired", (
        f"must stay expired when ping fails, got {result}"
    )


# ── 5. degenerate lark-cli output ────────────────────────────────────

def test_missing_lark_cli(monkeypatch):
    monkeypatch.setattr(_feishu.shutil, "which", lambda _: None)
    result = _feishu.check_feishu_auth()
    assert result["status"] == "missing"


def test_lark_cli_nonzero_rc(monkeypatch):
    monkeypatch.setattr(
        _feishu,
        "run_command_with_env",
        lambda cmd, **kw: _fake_completed(stderr="boom", rc=1),
    )
    result = _feishu.check_feishu_auth()
    assert result["status"] == "error"


def test_lark_cli_bad_json(monkeypatch):
    monkeypatch.setattr(
        _feishu,
        "run_command_with_env",
        lambda cmd, **kw: _fake_completed(stdout="not json"),
    )
    result = _feishu.check_feishu_auth()
    assert result["status"] == "error"
