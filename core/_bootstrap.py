"""
Shared Python path bootstrap for ClawSeat scripts.

Instead of each script doing its own sys.path.insert, import this module:

    from core._bootstrap import CLAWSEAT_ROOT

Or for scripts that can't import core/ directly (chicken-and-egg):

    import sys
    from pathlib import Path
    _root = Path(__file__).resolve().parents[N]  # adjust N
    sys.path.insert(0, str(_root))
    from core._bootstrap import CLAWSEAT_ROOT

This module:
1. Resolves CLAWSEAT_ROOT from env or filesystem
2. Adds core/ and CLAWSEAT_ROOT to sys.path (if not already)
3. Exposes CLAWSEAT_ROOT for other modules to use
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Resolve CLAWSEAT_ROOT
_SELF = Path(__file__).resolve()
CLAWSEAT_ROOT = Path(
    os.environ.get("CLAWSEAT_ROOT", str(_SELF.parents[1]))
)

# Ensure both core/ and CLAWSEAT_ROOT are importable
_paths_to_add = [
    str(CLAWSEAT_ROOT),
    str(CLAWSEAT_ROOT / "core"),
]
for p in _paths_to_add:
    if p not in sys.path:
        sys.path.insert(0, p)
