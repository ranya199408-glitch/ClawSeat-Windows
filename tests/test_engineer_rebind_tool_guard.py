"""Tests for T14: engineer rebind --tool guard (exit 2 on mismatch).

Covers:
  1. test_rebind_without_tool_arg_still_works — no --tool → returns 0
  2. test_rebind_with_matching_tool_works — --tool matches session.tool → returns 0
  3. test_rebind_with_mismatched_tool_errors_exit_2 — tool mismatch → returns 2, stderr
  4. test_docs_agent_admin_has_rebind_table — docs/AGENT_ADMIN.md contains expected content
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from agent_admin_crud import CrudHandlers


# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _caller_escalation_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / "caller.toml"
    profile.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "planner"',
                'display_name = "planner"',
                'role = "planner"',
                "dispatch_authority = false",
                "escalation_authority = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")

def _make_session(tool: str = "claude") -> SimpleNamespace:
    return SimpleNamespace(
        engineer_id="koder",
        tool=tool,
        project="install",
        auth_mode="oauth",
        provider="anthropic",
        runtime_dir="/tmp/fake-runtime",
        secret_file="",
        session="koder-session",
        workspace="/tmp/fake-ws",
    )


def _make_handlers(session_tool: str = "claude") -> tuple[CrudHandlers, MagicMock]:
    hooks = MagicMock()
    hooks.resolve_engineer_session.return_value = _make_session(tool=session_tool)
    hooks.load_project.return_value = MagicMock()
    hooks.identity_name.return_value = "claude.oauth.anthropic.koder"
    hooks.runtime_dir_for_identity.return_value = "/tmp/new-runtime"
    handlers = CrudHandlers(hooks)
    return handlers, hooks


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: no --tool arg → normal rebind, returns 0
# ══════════════════════════════════════════════════════════════════════════════

def test_rebind_without_tool_arg_still_works():
    handlers, hooks = _make_handlers("claude")
    # Simulate idempotent path: same auth_mode + provider → returns 0 early
    session = _make_session("claude")
    session.auth_mode = "oauth"
    session.provider = "anthropic"
    hooks.resolve_engineer_session.return_value = session

    args = SimpleNamespace(
        engineer="koder",
        project=None,
        mode="oauth",
        provider="anthropic",
        # no 'tool' attribute — matches real CLI behavior when flag not passed
    )
    result = handlers.engineer_rebind(args)
    assert result == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: --tool matches session.tool → guard passes, returns 0
# ══════════════════════════════════════════════════════════════════════════════

def test_rebind_with_matching_tool_works():
    handlers, hooks = _make_handlers("claude")
    session = _make_session("claude")
    session.auth_mode = "oauth"
    session.provider = "anthropic"
    hooks.resolve_engineer_session.return_value = session

    args = SimpleNamespace(
        engineer="koder",
        project=None,
        mode="oauth",
        provider="anthropic",
        tool="claude",  # matches session.tool
    )
    result = handlers.engineer_rebind(args)
    assert result == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: --tool mismatch → returns 2, stderr contains error detail
# ══════════════════════════════════════════════════════════════════════════════

def test_rebind_with_mismatched_tool_errors_exit_2(capsys):
    handlers, hooks = _make_handlers("claude")

    args = SimpleNamespace(
        engineer="koder",
        project=None,
        mode="api",
        provider="anthropic",
        tool="codex",  # mismatch: session.tool is "claude"
    )
    result = handlers.engineer_rebind(args)

    assert result == 2
    err = capsys.readouterr().err
    assert "rebind cannot change tool" in err
    assert "claude" in err
    assert "codex" in err


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: docs/AGENT_ADMIN.md exists and contains required content
# ══════════════════════════════════════════════════════════════════════════════

def test_docs_agent_admin_has_rebind_table():
    doc = _REPO / "docs" / "AGENT_ADMIN.md"
    assert doc.exists(), f"docs/AGENT_ADMIN.md not found at {doc}"
    text = doc.read_text(encoding="utf-8")
    assert "rebind vs delete+create" in text
    assert "cannot change tool" in text
    assert "engineer rebind" in text
    assert "engineer delete" in text
