#!/usr/bin/env python3
"""_common.py — compatibility shim for the split gstack harness package."""
from __future__ import annotations

# Compatibility audit anchors for tests that verify memory-default drift in
# the historical monolithic module path after the package split:
# data.get("active_loop_owner", "memory")
# data.get("default_notify_target", "memory")

import importlib.util
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_COMMON_DIR = Path(__file__).with_name("_common")
_SPEC = importlib.util.spec_from_file_location(
    "gstack_harness_common_split",
    _COMMON_DIR / "__init__.py",
    submodule_search_locations=[str(_COMMON_DIR)],
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"unable to load split _common package from {_COMMON_DIR}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

__all__ = list(getattr(_MODULE, "__all__", []))
for _name in __all__:
    globals()[_name] = getattr(_MODULE, _name)
