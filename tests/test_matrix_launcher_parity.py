from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
_LAUNCHER_AUTH = _REPO / "core" / "launchers" / "helpers" / "auth.sh"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest  # noqa: E402

from agent_admin_config import (  # noqa: E402
    LAUNCHER_AUTH_MAP,
    LAUNCHER_SECRET_TARGETS,
    SUPPORTED_RUNTIME_MATRIX,
    resolve_launcher_auth,
)
import agent_admin_session as aas  # noqa: E402


def _accepted_launcher_auth_pairs() -> set[tuple[str, str]]:
    text = _LAUNCHER_AUTH.read_text(encoding="utf-8")
    match = re.search(
        r'validate_auth_mode\(\)\s*\{.*?case "\$tool:\$auth" in(?P<body>.*?)\n\s*\*\)',
        text,
        re.DOTALL,
    )
    assert match, "validate_auth_mode case block not found"
    pairs = {
        (tool, auth)
        for tool, auth in re.findall(r"\b(claude|codex|gemini):([a-z0-9_-]+)\b", match.group("body"))
    }
    assert pairs, "no launcher auth pairs parsed from validate_auth_mode"
    return pairs


def _launcher_auth_for(tool: str, auth_mode: str, provider: str) -> str:
    service = aas.SessionService(MagicMock())
    session = SimpleNamespace(
        tool=tool,
        auth_mode=auth_mode,
        provider=provider,
        engineer_id="seat-1",
    )
    return service._launcher_auth_for(session)


def test_every_supported_matrix_tuple_maps_to_launcher_supported_auth() -> None:
    accepted = _accepted_launcher_auth_pairs()
    translated: dict[tuple[str, str, str], str] = {}

    for tool, auth_map in SUPPORTED_RUNTIME_MATRIX.items():
        for auth_mode, providers in auth_map.items():
            for provider in providers:
                launcher_auth = PLACEHOLDER(tool, auth_mode, provider)
                translated[(tool, auth_mode, provider)] = launcher_auth
                assert (tool, launcher_auth) in accepted, (
                    f"matrix tuple {tool}/{auth_mode}/{provider} translated to "
                    f"launcher auth {launcher_auth!r}, but validate_auth_mode "
                    f"does not accept {tool}:{launcher_auth}"
                )

    assert translated[("codex", "oauth", "openai")] == "chatgpt"
    assert translated[("gemini", "api", "google-api-key")] == "primary"
    assert translated[("claude", "api", "ark")] == "custom"
    assert translated[("claude", "ccr", "ccr-local")] == "custom"


def test_canonical_matrix_modes_remain_distinct_from_launcher_only_labels() -> None:
    accepted = _accepted_launcher_auth_pairs()
    matrix_tool_auth_pairs = {
        (tool, auth_mode)
        for tool, auth_map in SUPPORTED_RUNTIME_MATRIX.items()
        for auth_mode in auth_map
    }

    assert ("codex", "chatgpt") in accepted
    assert ("gemini", "primary") in accepted
    assert ("claude", "custom") in accepted

    assert ("codex", "chatgpt") not in matrix_tool_auth_pairs
    assert ("gemini", "primary") not in matrix_tool_auth_pairs
    assert ("claude", "custom") not in matrix_tool_auth_pairs


# ── resolve_launcher_auth parity tests ───────────────────────────────────────

def _matrix_tuples() -> list[tuple[str, str, str]]:
    return [
        (tool, auth_mode, provider)
        for tool, auth_map in SUPPORTED_RUNTIME_MATRIX.items()
        for auth_mode, providers in auth_map.items()
        for provider in providers
    ]


@pytest.mark.parametrize("tool,auth_mode,provider", _matrix_tuples())
def test_resolve_launcher_auth_matches_session_service(tool: str, auth_mode: str, provider: str) -> None:
    config_result = resolve_launcher_auth(tool, auth_mode, provider)
    session_result = _launcher_auth_for(tool, auth_mode, provider)
    assert config_result == session_result, (
        f"resolve_launcher_auth({tool!r}, {auth_mode!r}, {provider!r}) = {config_result!r} "
        f"but SessionService._launcher_auth_for = {session_result!r}"
    )


@pytest.mark.parametrize("tool,auth_mode,provider", _matrix_tuples())
def test_resolve_launcher_auth_output_accepted_by_launcher(tool: str, auth_mode: str, provider: str) -> None:
    accepted = _accepted_launcher_auth_pairs()
    label = resolve_launcher_auth(tool, auth_mode, provider)
    assert (tool, label) in accepted, (
        f"resolve_launcher_auth({tool!r}, {auth_mode!r}, {provider!r}) = {label!r} "
        f"not in validate_auth_mode accepted pairs"
    )


def test_launcher_auth_map_covers_all_matrix_tool_auth_modes() -> None:
    map_tool_auth_modes = {(tool, auth_mode) for (tool, auth_mode, _) in LAUNCHER_AUTH_MAP}
    for tool, auth_map in SUPPORTED_RUNTIME_MATRIX.items():
        for auth_mode in auth_map:
            assert (tool, auth_mode) in map_tool_auth_modes, (
                f"LAUNCHER_AUTH_MAP missing catch-all for {tool}/{auth_mode}"
            )


def test_launcher_secret_targets_keys_are_valid_tool_auth_pairs() -> None:
    accepted = _accepted_launcher_auth_pairs()
    for tool, launcher_auth in LAUNCHER_SECRET_TARGETS:
        assert (tool, launcher_auth) in accepted, (
            f"LAUNCHER_SECRET_TARGETS key ({tool!r}, {launcher_auth!r}) is not "
            f"a valid launcher auth pair"
        )
