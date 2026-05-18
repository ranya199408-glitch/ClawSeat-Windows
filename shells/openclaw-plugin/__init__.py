"""
ClawSeat OpenClaw distribution shell.

Entry point module that imports core + openclaw adapter shim and registers
the HarnessAdapter implementation when the OpenClaw adapter is available.

Note: The OpenClaw harness adapter is not yet implemented. This module
will fall back to the tmux-cli adapter until the OpenClaw adapter is available.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the core module path is available
CLAWSEAT_ROOT = os.environ.get("CLAWSEAT_ROOT")
if CLAWSEAT_ROOT:
    CLAWSEAT_ROOT = str(Path(CLAWSEAT_ROOT).expanduser().resolve())
else:
    # Derive from this file's location
    _self_path = Path(__file__).resolve()
    CLAWSEAT_ROOT = str(_self_path.parent.parent.parent)

if CLAWSEAT_ROOT not in sys.path:
    sys.path.insert(0, CLAWSEAT_ROOT)

# Import the adapter shim for bootstrap wiring
from shells.openclaw_plugin import adapter_shim

# Registry for available adapters
_ADAPTER_REGISTRY: dict[str, type] = {}


def register(adapter_name: str, adapter_class: type) -> None:
    """Register a HarnessAdapter implementation."""
    _ADAPTER_REGISTRY[adapter_name] = adapter_class


def get_adapter(name: str) -> type | None:
    """Get a registered HarnessAdapter by name."""
    return _ADAPTER_REGISTRY.get(name)


def list_adapters() -> list[str]:
    """List all registered adapter names."""
    return list(_ADAPTER_REGISTRY.keys())


# Attempt to register OpenClaw adapter (stub) when imported
# The actual OpenClaw adapter implementation will be loaded via adapter_shim
_loaded_adapter = adapter_shim.create_adapter()
if _loaded_adapter is not None:
    register("openclaw", type(_loaded_adapter))
