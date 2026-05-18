from __future__ import annotations

import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parent.parent
_INIT_KODER_DIR = _REPO / "core" / "skills" / "clawseat-install" / "scripts"
if str(_INIT_KODER_DIR) not in sys.path:
    sys.path.insert(0, str(_INIT_KODER_DIR))

import init_koder


def test_koder_hygiene_template_removed() -> None:
    assert not (_REPO / "core" / "templates" / "shared" / "TOOLS" / "koder-hygiene.md").exists()


def test_handoff_template_no_longer_points_at_koder_hygiene() -> None:
    text = (_REPO / "core" / "templates" / "shared" / "TOOLS" / "handoff.md").read_text(encoding="utf-8")
    assert "TOOLS/koder-hygiene.md" not in text
    assert "clawseat-koder" in text


def test_managed_files_are_four_file_workspace() -> None:
    assert init_koder.MANAGED_FILES == (
        "IDENTITY.md",
        "MEMORY.md",
        "USER.md",
        "WORKSPACE_CONTRACT.toml",
    )
    assert "TOOLS/koder-hygiene.md" in init_koder.OBSOLETE_FILES
