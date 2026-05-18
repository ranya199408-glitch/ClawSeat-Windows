"""C3 tests: bridge preflight runs before bridge-aware seats launch."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "lib"))
sys.path.insert(0, str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"))


@pytest.fixture(autouse=True)
def _clean_env(tmp_path, monkeypatch):
    for key in ("CLAWSEAT_FEISHU_GROUP_ID", "OPENCLAW_FEISHU_GROUP_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLAWSEAT_REAL_HOME", str(tmp_path))
    for name in ("bridge_preflight", "project_binding", "real_home", "_feishu", "_utils"):
        sys.modules.pop(name, None)
    yield tmp_path


def _load_bp():
    import bridge_preflight
    importlib.reload(bridge_preflight)
    return bridge_preflight


def _bind_install(home: Path, group="<FEISHU_GROUP_ID>") -> None:
    import project_binding
    importlib.reload(project_binding)
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(home))
        project_binding.bind_project(project="install", feishu_group_id=group)


def _fake_ok_auth():
    bp = _load_bp()
    return bp.PreflightCheck(name="lark_cli_auth", ok=True, detail="faked ok")


def _fake_bad_auth():
    bp = _load_bp()
    return bp.PreflightCheck(
        name="lark_cli_auth", ok=False,
        detail="faked failure",
        fix="lark-cli auth login",
    )


# ── seat_participates_in_bridge coverage ──────────────────────────────


def test_planner_dispatcher_role_participates():
    bp = _load_bp()
    assert bp.seat_participates_in_bridge(
        seat="planner", role="planner-dispatcher",
        heartbeat_owner="koder", active_loop_owner="planner",
        heartbeat_transport="tmux",
    )


def test_frontstage_supervisor_role_participates():
    bp = _load_bp()
    assert bp.seat_participates_in_bridge(
        seat="koder", role="frontstage-supervisor",
        heartbeat_owner="koder", active_loop_owner="planner",
        heartbeat_transport="openclaw",
    )


def test_openclaw_heartbeat_owner_participates_even_without_role():
    bp = _load_bp()
    assert bp.seat_participates_in_bridge(
        seat="koder", role="",
        heartbeat_owner="koder", active_loop_owner="planner",
        heartbeat_transport="openclaw",
    )


def test_tmux_heartbeat_owner_skips_preflight():
    """When heartbeat is tmux-only, koder doesn't send via Feishu — no preflight."""
    bp = _load_bp()
    assert not bp.seat_participates_in_bridge(
        seat="koder", role="",
        heartbeat_owner="koder", active_loop_owner="planner",
        heartbeat_transport="tmux",
    )


def test_builder_skips_preflight():
    bp = _load_bp()
    assert not bp.seat_participates_in_bridge(
        seat="builder-1", role="builder",
        heartbeat_owner="koder", active_loop_owner="planner",
        heartbeat_transport="openclaw",
    )


# ── run_bridge_preflight happy path ───────────────────────────────────


def test_preflight_green_when_binding_exists(_clean_env):
    _bind_install(_clean_env)
    bp = _load_bp()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_clean_env))
        result = bp.run_bridge_preflight(
            project="install", seat="planner",
            auth_checker=_fake_ok_auth,
        )
    assert result.ok, result.render()
    check_names = [c.name for c in result.checks]
    assert check_names == ["group_resolution", "lark_cli_auth", "envelope_render"]
    group_check = result.checks[0]
    assert "source=project_binding" in group_check.detail


# ── Red paths ─────────────────────────────────────────────────────────


def test_preflight_red_when_project_has_no_binding(_clean_env):
    bp = _load_bp()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_clean_env))
        result = bp.run_bridge_preflight(
            project="cartooner", seat="planner",
            auth_checker=_fake_ok_auth,
        )
    assert not result.ok
    group_check = result.checks[0]
    assert not group_check.ok
    assert "no feishu_group_id binding" in group_check.detail
    # Fix message points operators at the `agent-admin project bind` command.
    assert "agent-admin project bind" in group_check.fix


def test_preflight_red_when_auth_fails(_clean_env):
    _bind_install(_clean_env)
    bp = _load_bp()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_clean_env))
        result = bp.run_bridge_preflight(
            project="install", seat="planner",
            auth_checker=_fake_bad_auth,
        )
    assert not result.ok
    # group and envelope are OK; auth is the only FAIL.
    ok_by_name = {c.name: c.ok for c in result.checks}
    assert ok_by_name["group_resolution"] is True
    assert ok_by_name["lark_cli_auth"] is False
    assert ok_by_name["envelope_render"] is True


def test_skip_auth_marks_auth_as_skipped_but_green(_clean_env):
    """--skip-auth (or the test-time equivalent) keeps the other checks
    enforced so a user can still get group + envelope feedback."""
    _bind_install(_clean_env)
    bp = _load_bp()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_clean_env))
        result = bp.run_bridge_preflight(
            project="install", seat="planner", skip_auth=True,
        )
    assert result.ok
    auth_check = [c for c in result.checks if c.name == "lark_cli_auth"][0]
    assert auth_check.ok and "skipped" in auth_check.detail


# ── CLAWSEAT_FEISHU_ENABLED=0 short-circuit ──────────────────────────


def test_feishu_disabled_env_skips_all_checks(_clean_env, monkeypatch):
    """Setting CLAWSEAT_FEISHU_ENABLED=0 makes the whole preflight green
    without touching Feishu binding, lark-cli, or envelope code."""
    monkeypatch.setenv("CLAWSEAT_FEISHU_ENABLED", "0")
    bp = _load_bp()
    # Deliberately do NOT bind install — if the short-circuit is missing,
    # _check_group_resolution would fail and surface here.
    result = bp.run_bridge_preflight(project="install", seat="planner")
    assert result.ok
    assert len(result.checks) == 3
    names = {c.name for c in result.checks}
    # Schema parity with the normal path — see _check_envelope_renders()
    # which emits check name "envelope_render" (singular).
    assert names == {"group_resolution", "lark_cli_auth", "envelope_render"}
    for check in result.checks:
        assert check.ok
        assert "CLAWSEAT_FEISHU_ENABLED=0" in check.detail


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "False", "OFF"])
def test_feishu_disabled_env_accepts_common_falsy(_clean_env, monkeypatch, value):
    monkeypatch.setenv("CLAWSEAT_FEISHU_ENABLED", value)
    bp = _load_bp()
    result = bp.run_bridge_preflight(project="install", seat="planner")
    assert result.ok, f"{value!r} should disable preflight"


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
def test_feishu_enabled_env_does_not_skip(_clean_env, monkeypatch, value):
    """Non-falsy values must NOT short-circuit — existing behavior wins."""
    monkeypatch.setenv("CLAWSEAT_FEISHU_ENABLED", value)
    bp = _load_bp()
    # No binding and no auth_checker: group_resolution or auth should fail.
    result = bp.run_bridge_preflight(project="install", seat="planner", skip_auth=True)
    # Even with skip_auth=True, _check_group_resolution must have run
    # (no binding → fails). If the short-circuit leaked here, result.ok==True.
    assert not result.ok


# ── render() covers both green and red formatting ─────────────────────


def test_render_green_and_red(_clean_env):
    _bind_install(_clean_env)
    bp = _load_bp()
    with mock.patch("pwd.getpwuid") as m_pwd:
        m_pwd.return_value = mock.Mock(pw_dir=str(_clean_env))
        green = bp.run_bridge_preflight(
            project="install", seat="planner",
            auth_checker=_fake_ok_auth,
        )
        red = bp.run_bridge_preflight(
            project="install", seat="planner",
            auth_checker=_fake_bad_auth,
        )
    green_text = green.render()
    assert "[OK] group_resolution" in green_text
    assert "result: green" in green_text
    red_text = red.render()
    assert "[FAIL] lark_cli_auth" in red_text
    assert "result: RED" in red_text
    assert "fix: lark-cli auth login" in red_text
