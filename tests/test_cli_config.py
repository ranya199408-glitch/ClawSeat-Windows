"""Regression tests for CLI config management (audit P1).

Three invariants pinned:

1. GEMINI_API_PROVIDER_CONFIGS exists as a dict, structurally parallel
   to CLAUDE_ and CODEX_ variants. Empty today, but adding a Vertex or
   any other Gemini API provider must have an obvious home.

2. CodexProviderConfig + parse_codex_provider_config reject unknown
   fields at load time. Previously write_codex_api_config rendered from
   a raw dict; a typoed key was silently dropped and codex started
   without it, producing confusing runtime behavior.

3. _resolve_tool_bin records how each backend CLI was located (PATH /
   /opt/homebrew / bare). `unresolved_tool_bins()` lists every tool
   that fell back to the bare name; agent_admin.main warns about those
   on every invocation so users notice before exec fails.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest


_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ── H1: Gemini placeholder symmetry ──────────────────────────────────


def test_gemini_api_provider_configs_exists_and_is_dict() -> None:
    from core.scripts.agent_admin_config import GEMINI_API_PROVIDER_CONFIGS
    assert isinstance(GEMINI_API_PROVIDER_CONFIGS, dict)


def test_all_three_api_provider_dicts_are_symmetric() -> None:
    from core.scripts import agent_admin_config as cfg
    for name in (
        "CLAUDE_API_PROVIDER_CONFIGS",
        "CODEX_API_PROVIDER_CONFIGS",
        "GEMINI_API_PROVIDER_CONFIGS",
    ):
        assert hasattr(cfg, name), f"missing {name}"
        assert isinstance(getattr(cfg, name), dict)


def test_provider_url_helpers_resolve_canonical_defaults() -> None:
    from core.scripts.agent_admin_config import provider_default_base_url, tool_default_base_url

    assert tool_default_base_url("claude") == "https://api.anthropic.com"
    assert tool_default_base_url("codex") == "https://api.openai.com/v1"
    assert provider_default_base_url("claude", "minimax") == "https://api.minimaxi.com/anthropic"
    assert provider_default_base_url("claude", "ark") == "https://ark.cn-beijing.volces.com/api/coding"
    assert provider_default_base_url("claude", "xcode-best") == "https://xcode.best"
    assert provider_default_base_url("codex", "xcode-best") == "https://api.xcode.best/v1"


def test_provider_url_matches_uses_canonical_domain_markers() -> None:
    from core.scripts.agent_admin_config import provider_url_matches

    assert provider_url_matches("claude", "minimax", "https://api.minimaxi.com/anthropic")
    assert provider_url_matches("claude", "ark", "https://ark.cn-beijing.volces.com/api/coding")
    assert provider_url_matches("claude", "xcode-best", "https://xcode.best")
    assert provider_url_matches("codex", "xcode-best", "https://api.xcode.best/v1")
    assert not provider_url_matches("claude", "ark", "https://api.anthropic.com")


# ── H2: Codex config dataclass schema ────────────────────────────────


def test_codex_provider_config_parses_live_entries() -> None:
    """Every entry in CODEX_API_PROVIDER_CONFIGS must round-trip through
    the dataclass. If someone adds an entry with a bad field name this
    test catches it at CI time rather than at runtime."""
    from core.scripts.agent_admin_config import (
        CODEX_API_PROVIDER_CONFIGS,
        CodexProviderConfig,
        parse_codex_provider_config,
    )
    assert CODEX_API_PROVIDER_CONFIGS, "expected at least one provider"
    for name, raw in CODEX_API_PROVIDER_CONFIGS.items():
        cfg = parse_codex_provider_config(raw)
        assert isinstance(cfg, CodexProviderConfig), name
        assert cfg.model_provider and cfg.model and cfg.base_url and cfg.wire_api


def test_codex_provider_config_rejects_unknown_key() -> None:
    from core.scripts.agent_admin_config import parse_codex_provider_config
    raw = {
        "model_provider": "api111",
        "model": "gpt-5.5",
        "base_url": "https://x",
        "wire_api": "responses",
        "disable_response_storge": True,  # deliberate typo
    }
    with pytest.raises(ValueError, match="unknown codex provider config"):
        parse_codex_provider_config(raw)


def test_codex_provider_config_rejects_missing_required_field() -> None:
    from core.scripts.agent_admin_config import parse_codex_provider_config
    with pytest.raises(TypeError):
        parse_codex_provider_config({"model_provider": "x"})


def test_codex_render_uses_typed_fields_end_to_end(tmp_path: Path) -> None:
    """write_codex_api_config → parse → render produces valid TOML
    with values from the dataclass, not from the raw dict."""
    from core.scripts.agent_admin_config import CODEX_API_PROVIDER_CONFIGS
    from core.scripts.agent_admin_runtime import write_codex_api_config

    session = SimpleNamespace(provider="xcode-best")
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()

    def _write(path: Path, content: str, **_: object) -> None:
        path.write_text(content, encoding="utf-8")

    write_codex_api_config(
        session=session,
        codex_home=codex_home,
        project_repo=tmp_path,
        provider_configs=CODEX_API_PROVIDER_CONFIGS,
        write_text_fn=_write,
    )
    toml_text = (codex_home / "config.toml").read_text(encoding="utf-8")
    assert 'model_provider = "api111"' in toml_text
    assert 'model = "gpt-5.5"' in toml_text
    assert 'wire_api = "responses"' in toml_text
    assert "disable_response_storage = true" in toml_text


def test_codex_render_rejects_unknown_provider() -> None:
    from core.scripts.agent_admin_runtime import write_codex_api_config

    session = SimpleNamespace(provider="no-such-provider")
    with pytest.raises(ValueError, match="Unsupported Codex API provider"):
        write_codex_api_config(
            session=session,
            codex_home=Path("/tmp/ignored"),
            project_repo=Path("/tmp/ignored"),
            provider_configs={
                "xcode-best": {
                    "model_provider": "api111",
                    "model": "x",
                    "base_url": "y",
                    "wire_api": "z",
                }
            },
            write_text_fn=lambda *args, **kwargs: None,
        )


def test_codex_render_propagates_unknown_key_from_dict(tmp_path: Path) -> None:
    """If someone adds a typo to CODEX_API_PROVIDER_CONFIGS, the error
    surfaces at write time (not silently dropped)."""
    from core.scripts.agent_admin_runtime import write_codex_api_config

    session = SimpleNamespace(provider="broken")
    with pytest.raises(ValueError, match="unknown codex provider config"):
        write_codex_api_config(
            session=session,
            codex_home=tmp_path,
            project_repo=tmp_path,
            provider_configs={
                "broken": {
                    "model_provider": "api111",
                    "model": "gpt-5.5",
                    "base_url": "https://x",
                    "wire_api": "responses",
                    "reasoning": "high",  # typo: real name is model_reasoning_effort
                }
            },
            write_text_fn=lambda *a, **kw: None,
        )


# ── H3: Tool binary fallback observability ───────────────────────────


def test_tool_bin_source_is_populated_for_every_backend() -> None:
    """After import, every backend CLI has a recorded source so
    preflight/diagnostics can interrogate it."""
    from core.scripts.agent_admin_config import TOOL_BINARIES, tool_bin_source
    for name in TOOL_BINARIES:
        source = tool_bin_source(name)
        assert source in ("path", "homebrew", "bare"), f"{name}: unexpected source {source!r}"


def test_unresolved_tool_bins_surfaces_bare_fallback() -> None:
    """Re-import agent_admin_config in a subprocess with a PATH that
    cannot find any backend CLI: every tool should fall back to 'bare'
    and appear in unresolved_tool_bins()."""
    script = textwrap.dedent(
        """
        import os, sys
        sys.path.insert(0, os.path.join(os.getcwd(), "core", "scripts"))
        import agent_admin_config as cfg
        # Force the homebrew probe off and re-run the resolver so every
        # backend lands on the bare-name branch.
        cfg._TOOL_BIN_SOURCES = {}
        def _resolve(name: str) -> str:
            import shutil
            if shutil.which(name):
                cfg._TOOL_BIN_SOURCES[name] = "path"
                return shutil.which(name)
            cfg._TOOL_BIN_SOURCES[name] = "bare"
            return name
        cfg._resolve_tool_bin = _resolve
        for n in ("claude", "codex", "gemini"):
            cfg._resolve_tool_bin(n)
        print(",".join(cfg.unresolved_tool_bins()))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": "/tmp/nowhere"},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    missing = result.stdout.strip().split(",") if result.stdout.strip() else []
    assert missing == ["claude", "codex", "gemini"], missing


def test_warn_unresolved_tool_bins_prints_when_missing(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.scripts import agent_admin
    # agent_admin imports via the bare-name `agent_admin_config` module
    # (same directory on sys.path). Patch THAT entry; patching the
    # `core.scripts.agent_admin_config` copy would not be seen.
    import agent_admin_config as cfg

    monkeypatch.setattr(cfg, "_TOOL_BIN_SOURCES", {"codex": "bare", "claude": "path"})
    monkeypatch.delenv("CLAWSEAT_SUPPRESS_TOOL_BIN_WARNING", raising=False)
    agent_admin._warn_unresolved_tool_bins()
    captured = capsys.readouterr()
    assert "codex" in captured.err
    assert "backend CLI binaries not found on disk" in captured.err


def test_warn_unresolved_tool_bins_silent_when_all_resolved(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.scripts import agent_admin
    # Patch the bare-name module — same as the other two tests in this
    # block. The package-path copy (core.scripts.agent_admin_config) is a
    # DIFFERENT sys.modules entry, so patching it would not be seen by
    # `_warn_unresolved_tool_bins`'s internal `from agent_admin_config import`.
    import agent_admin_config as cfg

    monkeypatch.setattr(
        cfg, "_TOOL_BIN_SOURCES", {"codex": "path", "claude": "path", "gemini": "homebrew"}
    )
    agent_admin._warn_unresolved_tool_bins()
    assert capsys.readouterr().err == ""


def test_warn_unresolved_tool_bins_respects_suppress_env(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.scripts import agent_admin
    # agent_admin imports via the bare-name `agent_admin_config` module
    # (same directory on sys.path). Patch THAT entry; patching the
    # `core.scripts.agent_admin_config` copy would not be seen.
    import agent_admin_config as cfg

    monkeypatch.setattr(cfg, "_TOOL_BIN_SOURCES", {"codex": "bare"})
    monkeypatch.setenv("CLAWSEAT_SUPPRESS_TOOL_BIN_WARNING", "1")
    agent_admin._warn_unresolved_tool_bins()
    assert capsys.readouterr().err == ""
