"""Test that _utils.py raises a clear operator-facing error when both tomllib
and tomli are unavailable (Python <3.11 without tomli installed).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_UTILS_PATH = Path(__file__).resolve().parents[1] / "core/skills/gstack-harness/scripts/_utils.py"


def test_missing_tomllib_and_tomli_raises_friendly_error():
    """When both tomllib and tomli are absent, the ModuleNotFoundError message
    names the minimum Python version and the pip install remedy."""
    # Save and remove cached modules so the file is re-executed.
    saved: dict = {}
    for key in ("tomllib", "tomli", "_utils"):
        saved[key] = sys.modules.pop(key, None)

    # Block both tomllib and tomli by setting sys.modules entries to None,
    # which causes Python to treat them as explicitly absent (import raises ImportError).
    sys.modules["tomllib"] = None  # type: ignore[assignment]
    sys.modules["tomli"] = None  # type: ignore[assignment]

    try:
        spec = importlib.util.spec_from_file_location("_utils_test_isolated", _UTILS_PATH)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            assert False, "Expected ModuleNotFoundError was not raised"
        except ModuleNotFoundError as exc:
            msg = str(exc)
            assert "Python 3.11" in msg, f"Missing Python version hint in error: {msg!r}"
            assert "pip install tomli" in msg, f"Missing install remedy in error: {msg!r}"
    finally:
        # Restore sys.modules exactly as before.
        for key, val in saved.items():
            if val is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = val
        # Clean up the isolated module we loaded.
        sys.modules.pop("_utils_test_isolated", None)
