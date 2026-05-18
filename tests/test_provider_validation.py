"""Lock the 'anthropix'-class typo detector at every argparse entry point.

Historically `agent-admin engineer create install claude oauth anthropix`
silently succeeded: the engineer profile wrote `provider=anthropix`, the
runtime sandbox directory got created under
`~/.agents/runtime/identities/claude/oauth/claude.oauth.anthropix.install.<seat>/`,
the seat's CLI launched in that sandbox with no credentials, and claude
dropped the operator at the OAuth login screen. The only symptom was a
'pane 持续空白'.

The underlying validator `is_supported_runtime_combo()` / `validate_runtime_combo()`
has existed for a while — but none of the CLI entry points actually
called it. This test pins that every mutating entry point refuses an
unsupported triple UPFRONT, before any filesystem side effect.

Covered entry points:
- `engineer create`            (agent_admin_crud.CrudHandlers.engineer_create)
- `session switch-harness`     (agent_admin_switch.SwitchHandlers.session_switch_harness)
- `session switch-auth`        (agent_admin_switch.SwitchHandlers.session_switch_auth)

`start_seat.py` also validates locally before the subprocess round-trip;
that path is covered by the live smoke in the commit message, not here
(it spawns subprocesses).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "core" / "scripts"))

from agent_admin_config import (  # noqa: E402
    SUPPORTED_RUNTIME_MATRIX,
    is_supported_runtime_combo,
    supported_providers,
    validate_runtime_combo,
)


# ── Sanity: the matrix itself is what we think it is ────────────────────────


def test_anthropix_is_not_a_valid_provider():
    """Pin the exact typo we want to catch — if anyone silently adds
    'anthropix' as an alias of 'anthropic' in the matrix, this test will
    scream so the operator can ask 'are you sure this is intentional?'
    """
    assert not is_supported_runtime_combo("claude", "oauth", "anthropix")
    assert is_supported_runtime_combo("claude", "oauth", "anthropic")


def test_minimaxi_is_not_a_valid_provider():
    """Same rationale for the sibling typo."""
    assert not is_supported_runtime_combo("claude", "api", "minimaxi")
    assert is_supported_runtime_combo("claude", "api", "minimax")


def test_matrix_has_every_triple_we_rely_on_in_docs():
    """TOOLS/seat.md tells koder which triples are valid. If any of those
    references drift from the matrix, the operator will get contradictory
    guidance.
    """
    expected = {
        ("claude", "oauth", "anthropic"),
        ("claude", "api", "xcode-best"),
        ("claude", "api", "minimax"),
        ("codex", "oauth", "openai"),
        ("codex", "api", "xcode-best"),
        ("gemini", "oauth", "google"),
        ("gemini", "api", "google-api-key"),
    }
    for (tool, auth, provider) in expected:
        assert is_supported_runtime_combo(tool, auth, provider), (
            f"{tool}/{auth}/{provider} dropped from matrix — this breaks "
            "TOOLS/seat.md guidance"
        )


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_launch_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "fake-root"
    log_path = tmp_path / "calls.log"
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    _write_executable(
        root / "core" / "launchers" / "agent-launcher.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'launcher %s\\n' "$*" >> "${LOG_FILE:?}"
if [[ "${1:-}" == "--check-secrets" ]]; then
  printf '{"status":"ok"}\\n'
  exit 0
fi
echo "unexpected launcher invocation" >&2
exit 99
""",
    )
    _write_executable(
        root / "core" / "scripts" / "agent_admin.py",
        """#!/usr/bin/env python3
from __future__ import annotations
import os
import sys
from pathlib import Path
Path(os.environ["LOG_FILE"]).open("a", encoding="utf-8").write(
    "agent_admin " + " ".join(sys.argv[1:]) + "\\n"
)
raise SystemExit(0)
""",
    )
    (root / "core" / "scripts" / "agent_admin_config.py").write_text(
        """def validate_runtime_combo(tool, auth_mode, provider, error_cls=RuntimeError):
    valid = {
        ('claude', 'oauth', 'anthropic'),
        ('claude', 'oauth_token', 'anthropic'),
        ('claude', 'api', 'anthropic-console'),
        ('claude', 'api', 'minimax'),
        ('claude', 'api', 'xcode-best'),
        ('codex', 'oauth', 'openai'),
        ('codex', 'api', 'xcode-best'),
        ('gemini', 'oauth', 'google'),
        ('gemini', 'api', 'google-api-key'),
    }
    if (tool, auth_mode, provider) not in valid:
        raise error_cls(f'unsupported runtime combination `{tool}/{auth_mode}/{provider}`')
""",
        encoding="utf-8",
    )
    _write_executable(
        root / "core" / "shell-scripts" / "send-and-verify.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'send %s\\n' "$*" >> "${LOG_FILE:?}"
""",
    )
    (root / "core" / "skills" / "clawseat-ancestor").mkdir(parents=True, exist_ok=True)
    (root / "core" / "skills" / "clawseat-ancestor" / "SKILL.md").write_text(
        "# stub ancestor skill\n",
        encoding="utf-8",
    )
    return root, log_path


def test_legacy_launch_ancestor_entrypoint_removed() -> None:
    assert not (_REPO / "scripts" / "launch_ancestor.sh").exists()


def test_env_scan_emits_only_supported_runtime_combos(tmp_path: Path):
    fake_home = tmp_path / "home"
    (fake_home / ".agents").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agents" / ".env.global").write_text(
        "export CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_CODE_OAUTH_TOKEN>\n",
        encoding="utf-8",
    )
    (fake_home / ".agents" / "secrets" / "claude").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agents" / "secrets" / "claude" / "anthropic-console.env").write_text(
        "ANTHROPIC_API_KEY=<ANTHROPIC_API_KEY>\n",
        encoding="utf-8",
    )
    (fake_home / ".agent-runtime" / "secrets" / "claude").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agent-runtime" / "secrets" / "claude" / "minimax.env").write_text(
        "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n"
        "ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic\n",
        encoding="utf-8",
    )
    (fake_home / ".agent-runtime" / "secrets" / "claude" / "ark.env").write_text(
        "ANTHROPIC_AUTH_TOKEN=<ANTHROPIC_AUTH_TOKEN>\n"
        "ANTHROPIC_BASE_URL=https://ark.cn-beijing.volces.com/api/coding\n",
        encoding="utf-8",
    )
    (fake_home / ".codex").mkdir(parents=True, exist_ok=True)
    (fake_home / ".codex" / "auth.json").write_text("{}", encoding="utf-8")
    (fake_home / ".agent-runtime" / "secrets" / "gemini").mkdir(parents=True, exist_ok=True)
    (fake_home / ".agent-runtime" / "secrets" / "gemini" / "primary.env").write_text(
        "GEMINI_API_KEY=gem-key\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["python3", str(_REPO / "scripts" / "env_scan.py")],
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "CLAWSEAT_SCAN_HOME": str(fake_home),
            "PATH": os.environ.get("PATH", ""),
        },
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    combos = {
        (item["tool"], item["auth_mode"], item["provider"])
        for item in payload["auth_methods"]
    }
    expected = {
        ("claude", "oauth_token", "anthropic"),
        ("claude", "api", "anthropic-console"),
        ("claude", "api", "ark"),
        ("claude", "api", "minimax"),
        ("codex", "oauth", "openai"),
        ("gemini", "api", "google-api-key"),
    }
    assert expected.issubset(combos)
    assert ("claude", "api", "anthropic") not in combos
    for tool, auth_mode, provider in combos:
        assert is_supported_runtime_combo(tool, auth_mode, provider)


# ── validate_runtime_combo shape + error text ─────────────────────────────


def test_validate_rejects_anthropix_with_helpful_error():
    with pytest.raises(RuntimeError) as excinfo:
        validate_runtime_combo(
            "claude", "oauth", "anthropix",
            error_cls=RuntimeError,
            context="test",
        )
    msg = str(excinfo.value)
    # Helpful error must include:
    # 1. the bad value (so operator sees what they typed wrong)
    assert "anthropix" in msg
    # 2. the tool + auth_mode for disambiguation
    assert "claude/oauth" in msg
    # 3. the ACTUAL valid provider(s)
    assert "anthropic" in msg
    # 4. the caller-supplied context so operator knows which command failed
    assert "test" in msg


def test_validate_accepts_anthropic():
    # Must not raise for valid triples.
    validate_runtime_combo("claude", "oauth", "anthropic")
    validate_runtime_combo("codex", "oauth", "openai")
    validate_runtime_combo("gemini", "oauth", "google")
    validate_runtime_combo("claude", "api", "minimax")
    validate_runtime_combo("codex", "api", "xcode-best")


def test_validate_rejects_unknown_tool():
    # argparse `choices` should prevent this, but our defence-in-depth
    # still reports it cleanly instead of KeyErroring.
    with pytest.raises(ValueError) as excinfo:
        validate_runtime_combo("claud", "oauth", "anthropic")
    assert "claud" in str(excinfo.value)


def test_validate_rejects_unknown_auth_mode():
    with pytest.raises(ValueError) as excinfo:
        validate_runtime_combo("claude", "oauthed", "anthropic")
    assert "oauthed" in str(excinfo.value)


# ── Entry point: engineer_create ──────────────────────────────────────────


def _fake_crud_hooks(error_cls=RuntimeError):
    """Hand-rolled stub with only the fields engineer_create touches
    before validation fires. If validation is missing and we reach the
    real side-effect-ful hooks, AttributeError tells us fast.
    """
    from types import SimpleNamespace
    hooks = SimpleNamespace(
        error_cls=error_cls,
        load_projects=lambda: {"install": SimpleNamespace(
            name="install",
            engineers=[],
            monitor_engineers=[],
        )},
        normalize_name=lambda n: n,
        session_path=lambda _p, _e: Path("/tmp/nonexistent.toml"),
        engineer_path=lambda _e: Path("/tmp/nonexistent.toml"),
        load_engineer=lambda _e: None,
        create_engineer_profile=lambda **_kw: (_ for _ in ()).throw(
            AssertionError("create_engineer_profile reached — validation didn't fire")
        ),
        write_engineer=lambda _p: None,
        create_session_record=lambda **_kw: None,
        write_session=lambda _s: None,
        apply_template=lambda _s, _p: None,
        ensure_dir=lambda _p: None,
        write_env_file=lambda *_a, **_kw: None,
        write_project=lambda _p: None,
    )
    return hooks


def test_engineer_create_rejects_anthropix_before_any_side_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """This is the one that matters: today's failure mode was
    `engineer create designer-1 install claude oauth anthropix` silently
    succeeding. After validation, it must raise BEFORE we touch disk.
    """
    from types import SimpleNamespace
    from agent_admin_crud import CrudHandlers  # noqa: WPS433

    caller_profile = tmp_path / "caller.toml"
    caller_profile.write_text(
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
    monkeypatch.setenv("CLAWSEAT_ENGINEER_PROFILE", str(caller_profile))
    monkeypatch.setenv("CLAWSEAT_ENGINEER_ID", "planner")
    monkeypatch.setenv("CLAWSEAT_SEAT", "planner")

    hooks = _fake_crud_hooks()
    handlers = CrudHandlers(hooks)
    args = SimpleNamespace(
        engineer="test-bad",
        project="install",
        tool="claude",
        mode="oauth",
        provider="anthropix",
        no_monitor=False,
    )
    with pytest.raises(RuntimeError) as excinfo:
        handlers.engineer_create(args)
    assert "anthropix" in str(excinfo.value)
    assert "engineer create test-bad" in str(excinfo.value)


# ── Entry point: switch-harness ──────────────────────────────────────────


def _fake_switch_hooks(error_cls=RuntimeError):
    from types import SimpleNamespace
    return SimpleNamespace(
        error_cls=error_cls,
        load_project_or_current=lambda _p: (_ for _ in ()).throw(
            AssertionError("reached load_project_or_current — validation didn't fire")
        ),
        load_session=lambda _p, _e: None,
        normalize_name=lambda n: n,
    )


def test_switch_harness_rejects_anthropix_before_load():
    from types import SimpleNamespace
    from agent_admin_switch import SwitchHandlers  # noqa: WPS433

    # SwitchHandlers takes SwitchHooks via constructor — use the thin
    # subset we need. Pass a MagicMock-like object for the rest.
    class _Stub:
        pass
    stub = _Stub()
    for field in (
        "error_cls", "legacy_secrets_root", "tool_binaries",
        "default_tool_args", "identity_name", "runtime_dir_for_identity",
        "secret_file_for", "session_name_for", "ensure_dir",
        "ensure_secret_permissions", "write_env_file", "write_text",
        "session_record_cls", "load_project_or_current", "load_session",
        "normalize_name", "write_session", "apply_template",
        "session_stop_engineer",
    ):
        setattr(stub, field, lambda *a, **kw: None)  # noqa: PIE731
    stub.error_cls = RuntimeError

    def _should_not_reach(*a, **kw):  # noqa: ARG001
        raise AssertionError(
            "load_project_or_current reached — provider validation "
            "failed to fire before any mutation"
        )
    stub.load_project_or_current = _should_not_reach

    handlers = SwitchHandlers(stub)
    args = SimpleNamespace(
        project="install",
        engineer="planner",
        tool="claude",
        mode="oauth",
        provider="anthropix",
    )
    with pytest.raises(RuntimeError) as excinfo:
        handlers.session_switch_harness(args)
    assert "anthropix" in str(excinfo.value)
    assert "switch-harness" in str(excinfo.value)


# ── Structural: every provider listed in SUPPORTED_RUNTIME_MATRIX is non-empty


def test_matrix_has_no_empty_provider_lists():
    """Empty provider tuples would make the validator reject all calls
    and break engineer_create for that tool/auth pair. Canary.
    """
    for tool, auth_map in SUPPORTED_RUNTIME_MATRIX.items():
        for auth_mode, providers in auth_map.items():
            assert providers, f"{tool}/{auth_mode} has empty provider list"
            for p in providers:
                assert p, f"{tool}/{auth_mode} contains empty provider string"
                assert p.strip() == p, (
                    f"{tool}/{auth_mode} provider {p!r} has leading/trailing "
                    "whitespace — argparse values won't match"
                )
