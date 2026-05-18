"""Regression tests for Batch A polish items.

Covers:

- **M1** — three shells/*/adapter_shim.py were 95% duplicated; they now
  all delegate to shells/_shim_base.py. Pin the behaviour each bundle
  still advertises (shell name, metadata shape, `get_current_adapter_name`
  survives on openclaw-plugin).

- **L2** — HarnessAdapter abstract methods no longer carry a redundant
  `raise NotImplementedError`; instantiating a subclass that forgets a
  method still raises TypeError at construction time.

- **L3** — core/__init__.py now ships an __all__ so the intended public
  surface is explicit. Pin that list so additions/removals go through a
  code review.

- **L7** — tmux-cli adapter was referenced from three bundle shims but
  had no direct smoke test. Add one: load the module, check that it
  exposes the expected class + construction signature, without
  touching tmux.

- **L11** — codex-bundle historically only ships AGENTS.md. A
  SKILL.md → AGENTS.md symlink was added so Claude-Code-style skill
  discovery also finds this bundle.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _load_shim(bundle_name: str):
    script = _REPO / "shells" / bundle_name / "adapter_shim.py"
    spec = importlib.util.spec_from_file_location(f"shim_{bundle_name}", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Give each test its own fresh copy so the shared _shim_base
    # sys.path side effect doesn't leak assertions across loads.
    spec.loader.exec_module(module)
    return module


# ── M1: shells/*/adapter_shim.py are thin wrappers over _shim_base ──


def test_shared_shim_base_exists() -> None:
    assert (_REPO / "shells" / "_shim_base.py").exists()


def test_all_three_shims_import_and_report_shell_name() -> None:
    expected = {
        "claude-bundle": "claude-bundle",
        "codex-bundle": "codex-bundle",
        "openclaw-plugin": "openclaw-plugin",
    }
    for bundle, shell_name in expected.items():
        mod = _load_shim(bundle)
        meta = mod.shell_metadata()
        assert meta["shell"] == shell_name
        assert meta["adapter"].endswith("adapters/harness/tmux-cli/adapter.py")
        assert meta["contract"].endswith("core/harness_adapter.py")


def test_claude_and_codex_bundles_ship_core_skill_metadata() -> None:
    for bundle in ("claude-bundle", "codex-bundle"):
        mod = _load_shim(bundle)
        meta = mod.shell_metadata()
        assert "core_skill" in meta, f"{bundle} should preserve pre-M1 core_skill key"
        assert meta["core_skill"].endswith("core/skills/gstack-harness/SKILL.md")


def test_openclaw_bundle_drops_core_skill_as_before() -> None:
    mod = _load_shim("openclaw-plugin")
    meta = mod.shell_metadata()
    assert "core_skill" not in meta, "openclaw-plugin historically omitted this key"


def test_openclaw_bundle_preserves_get_current_adapter_name() -> None:
    mod = _load_shim("openclaw-plugin")
    assert mod.get_current_adapter_name() == "tmux-cli"


def test_claude_and_codex_bundles_do_not_grow_the_openclaw_only_helper() -> None:
    for bundle in ("claude-bundle", "codex-bundle"):
        mod = _load_shim(bundle)
        assert not hasattr(mod, "get_current_adapter_name"), (
            f"{bundle} did not previously define get_current_adapter_name; "
            "keep the surfaces asymmetric until a real need arises."
        )


# ── L2: abstract methods without redundant NotImplementedError ──


def test_harness_adapter_abstract_contract_raises_at_construction() -> None:
    from core.harness_adapter import HarnessAdapter, SessionHandle

    class Incomplete(HarnessAdapter):  # missing every abstract method
        pass

    with pytest.raises(TypeError, match="abstract method"):
        Incomplete()  # type: ignore[abstract]


def test_harness_adapter_source_has_no_notimplementederror() -> None:
    """The L2 fix dropped the redundant bodies; guard against regressions
    where someone 'completes' an abstract method by adding it back.
    Only non-comment lines are inspected — the explanatory block that
    references NotImplementedError in prose is allowed."""
    source = (_REPO / "core" / "harness_adapter.py").read_text(encoding="utf-8")
    offending = [
        line for line in source.splitlines()
        if "raise NotImplementedError" in line and not line.lstrip().startswith("#")
    ]
    assert not offending, (
        "HarnessAdapter abstract bodies should stay bare `...`; ABC already "
        "enforces subclass implementation at construction time. Offending "
        f"lines:\n  " + "\n  ".join(offending)
    )


# ── L3: core/__init__.py public surface ──


def test_core_init_exports_expected_public_surface() -> None:
    import core

    public = {
        "resolve",
        "harness_adapter",
        "bootstrap_receipt",
        "preflight",
        "skill_registry",
        "adapter",
        "engine",
        "transport",
        "migration",
    }
    assert set(core.__all__) == public, (
        f"core.__all__ changed unexpectedly. diff:\n"
        f"  added:   {set(core.__all__) - public}\n"
        f"  removed: {public - set(core.__all__)}"
    )


# ── L7: tmux-cli adapter smoke ──


def test_tmux_cli_adapter_module_exposes_expected_class() -> None:
    adapter_path = _REPO / "adapters" / "harness" / "tmux-cli" / "adapter.py"
    assert adapter_path.exists(), "tmux-cli adapter is referenced by every shell bundle"

    spec = importlib.util.spec_from_file_location("tmux_cli_adapter_smoke", adapter_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cls = getattr(module, "TmuxCliAdapter", None)
    assert cls is not None, "TmuxCliAdapter is the contract name used by shells/"

    # Construct without hitting tmux — should accept the three kwargs
    # every bundle passes through. If the constructor signature drifts
    # the bundles would silently break.
    instance = cls(agents_root=None, sessions_root=None, workspaces_root=None)
    assert instance is not None


# ── L11: codex-bundle SKILL.md → AGENTS.md symlink ──


def test_codex_bundle_ships_skill_md_alias() -> None:
    codex_dir = _REPO / "shells" / "codex-bundle"
    skill_md = codex_dir / "SKILL.md"
    agents_md = codex_dir / "AGENTS.md"
    assert agents_md.exists(), "codex-bundle has always shipped AGENTS.md"
    assert skill_md.exists() or skill_md.is_symlink(), (
        "codex-bundle should expose a SKILL.md so Claude-Code-style skill "
        "discovery also picks up this bundle (audit L11)."
    )
    # Either a symlink pointing at AGENTS.md or a verbatim copy is OK;
    # make sure the content tracks.
    assert skill_md.read_text(encoding="utf-8") == agents_md.read_text(encoding="utf-8")
