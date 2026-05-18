"""Adapter shim for the Codex CLI ClawSeat bundle.

Thin wrapper around `shells/_shim_base.py` — see that module for the
shared logic and the history of the M1 de-duplication audit.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


_SHELLS_DIR = Path(__file__).resolve().parent.parent
if str(_SHELLS_DIR) not in sys.path:
    sys.path.insert(0, str(_SHELLS_DIR))

from _shim_base import (  # noqa: E402
    create_adapter as _create_adapter,
    load_harness_adapter_types as _load_harness_adapter_types,
    load_tmux_cli_adapter_module as _load_tmux_cli_adapter_module,
    resolve_clawseat_root as _resolve_clawseat_root,
    shell_metadata as _shell_metadata,
)


def resolve_clawseat_root() -> Path:
    return _resolve_clawseat_root(Path(__file__))


def load_harness_adapter_types() -> Any:
    return _load_harness_adapter_types(resolve_clawseat_root())


def load_tmux_cli_adapter_module() -> Any:
    return _load_tmux_cli_adapter_module(resolve_clawseat_root())


def create_adapter(
    *,
    agents_root: str | Path | None = None,
    sessions_root: str | Path | None = None,
    workspaces_root: str | Path | None = None,
) -> Any:
    return _create_adapter(
        resolve_clawseat_root(),
        agents_root=agents_root,
        sessions_root=sessions_root,
        workspaces_root=workspaces_root,
    )


def shell_metadata() -> dict[str, str]:
    return _shell_metadata(resolve_clawseat_root(), shell="codex-bundle")
