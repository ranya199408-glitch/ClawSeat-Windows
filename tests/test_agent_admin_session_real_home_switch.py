from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import agent_admin_session as aas  # noqa: E402


_HELPERS_PATH = Path(__file__).with_name("test_agent_admin_session_isolation.py")
_HELPERS_SPEC = importlib.util.spec_from_file_location("test_agent_admin_session_isolation_helpers", _HELPERS_PATH)
assert _HELPERS_SPEC is not None and _HELPERS_SPEC.loader is not None
_HELPERS = importlib.util.module_from_spec(_HELPERS_SPEC)
_HELPERS_SPEC.loader.exec_module(_HELPERS)

_make_session = _HELPERS._make_session
_make_service = _HELPERS._make_service


def test_launcher_paths_use_real_home_not_sandbox_path_home(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sandbox_home = tmp_path / "sandbox-home"
    real_home = tmp_path / "real-home"
    sandbox_home.mkdir()
    real_home.mkdir()

    monkeypatch.setattr(aas.Path, "home", classmethod(lambda cls: sandbox_home))
    monkeypatch.setattr(aas, "real_user_home", lambda: real_home)

    session = _make_session(
        tmp_path,
        engineer_id="planner-1",
        tool="claude",
        auth_mode="oauth_token",
        provider="anthropic",
    )
    svc, _ = _make_service(tmp_path, session)

    assert svc._launcher_secret_target(session, "oauth_token") == real_home / ".agents" / ".env.global"
    assert svc._launcher_runtime_dir(session, "oauth_token") == (
        real_home
        / ".agent-runtime"
        / "identities"
        / "claude"
        / "oauth_token"
        / f"oauth_token-{session.session}"
    )
