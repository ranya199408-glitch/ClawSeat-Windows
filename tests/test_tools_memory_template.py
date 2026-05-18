"""T22: memory learning channel docs — TOOLS/memory.md template tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = str(_REPO / "core" / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def test_memory_md_exists_in_template():
    """core/templates/shared/TOOLS/memory.md must exist, be non-empty, and contain required anchors."""
    memory_md = _REPO / "core" / "templates" / "shared" / "TOOLS" / "memory.md"
    assert memory_md.exists(), f"Missing: {memory_md}"
    content = memory_md.read_text(encoding="utf-8")
    assert content.strip(), "memory.md is empty"
    assert "L3 Reflector" in content, "memory.md must describe the L3 Reflector contract"
    assert "notify_seat.py --target memory" in content, \
        "memory.md must document notify_seat.py --target memory (learning channel)"
    assert "query_memory.py" in content, \
        "memory.md must document query_memory.py (direct query mode)"


def test_memory_md_referenced_in_template_toml():
    """core/templates/gstack-harness/template.toml must reference TOOLS/memory.md."""
    template_toml = _REPO / "core" / "templates" / "gstack-harness" / "template.toml"
    assert template_toml.exists(), f"Missing: {template_toml}"
    content = template_toml.read_text(encoding="utf-8")
    assert "TOOLS/memory.md" in content, \
        "template.toml must reference TOOLS/memory.md (workspace_tools or similar)"


def test_init_koder_copies_memory_md(tmp_path):
    """After init_koder runs, workspace-<agent>/TOOLS/memory.md must exist."""
    # init_koder.py renders TOOLS/memory.md via render_tools_memory() at line 224.
    # Verify the managed_files list includes TOOLS/memory.md and the render function exists.
    init_koder_path = _REPO / "core" / "skills" / "clawseat-install" / "scripts" / "init_koder.py"
    assert init_koder_path.exists(), f"Missing: {init_koder_path}"
    content = init_koder_path.read_text(encoding="utf-8")
    assert '"TOOLS/memory.md"' in content or "'TOOLS/memory.md'" in content, \
        "init_koder.py must include TOOLS/memory.md in its managed files list"
    assert "render_tools_memory" in content, \
        "init_koder.py must have a render_tools_memory function that generates TOOLS/memory.md"
