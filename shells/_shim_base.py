"""Shared adapter-shim logic used by every ClawSeat shell bundle.

Before this module existed, `shells/claude-bundle/adapter_shim.py`,
`shells/codex-bundle/adapter_shim.py`, and
`shells/openclaw-plugin/adapter_shim.py` carried 95% identical code —
`resolve_clawseat_root`, `_load_module`, `load_harness_adapter_types`,
`load_tmux_cli_adapter_module`, `create_adapter` — that already drifted
(openclaw-plugin had a `get_current_adapter_name` helper and dropped
`core_skill` from its metadata; a fix in one copy never propagated to
the others). Audit M1.

Each per-shell `adapter_shim.py` now just re-exports the helpers and
calls `shell_metadata(shell=...)` with its own bundle name.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


def resolve_clawseat_root(script_path: Path) -> Path:
    """Resolve CLAWSEAT_ROOT via shared `core/resolve.py`.

    Walks from *script_path* (the caller's ``__file__``) two levels up
    to reach the repo root — every shell bundle lives at
    ``shells/<bundle-name>/adapter_shim.py``.
    """
    repo_root = script_path.resolve().parents[2]
    core_path = str(repo_root / "core")
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    from resolve import resolve_clawseat_root as _shared  # type: ignore[import-not-found]
    return _shared()


def load_module(name: str, path: Path) -> Any:
    """Load a Python module directly from *path* under the given *name*.

    Used to pull the tmux-cli adapter + the harness-adapter contract
    without polluting the top-level package namespace.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_harness_adapter_types(root: Path) -> Any:
    return load_module("clawseat_core_harness_adapter", root / "core" / "harness_adapter.py")


def load_tmux_cli_adapter_module(root: Path) -> Any:
    return load_module(
        "clawseat_tmux_cli_adapter",
        root / "adapters" / "harness" / "tmux-cli" / "adapter.py",
    )


def create_adapter(
    root: Path,
    *,
    agents_root: str | Path | None = None,
    sessions_root: str | Path | None = None,
    workspaces_root: str | Path | None = None,
) -> Any:
    module = load_tmux_cli_adapter_module(root)
    return module.TmuxCliAdapter(
        agents_root=agents_root,
        sessions_root=sessions_root,
        workspaces_root=workspaces_root,
    )


def shell_metadata(
    root: Path,
    *,
    shell: str,
    include_core_skill: bool = True,
) -> dict[str, str]:
    """Standard shell metadata payload.

    Historically claude-bundle + codex-bundle reported a ``core_skill``
    entry while openclaw-plugin omitted it. The behavior is preserved
    via *include_core_skill*: each shell can opt out explicitly, but
    the default is on so we don't silently drop the key for the two
    bundles that have always shipped it.
    """
    metadata = {
        "shell": shell,
        "clawseat_root": str(root),
        "adapter": str(root / "adapters" / "harness" / "tmux-cli" / "adapter.py"),
        "contract": str(root / "core" / "harness_adapter.py"),
    }
    if include_core_skill:
        metadata["core_skill"] = str(root / "core" / "skills" / "gstack-harness" / "SKILL.md")
    return metadata
