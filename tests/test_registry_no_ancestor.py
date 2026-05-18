from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_list_engineers_hides_deprecated_ancestor_registry_entry() -> None:
    result = subprocess.run(
        [sys.executable, str(_REPO / "core" / "scripts" / "agent_admin.py"), "list-engineers"],
        cwd=_REPO,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "Ancestor" not in result.stdout
    assert "ancestor" not in result.stdout


def test_agent_admin_config_no_longer_defines_ancestor_seat() -> None:
    text = (_REPO / "core" / "scripts" / "agent_admin_config.py").read_text(encoding="utf-8")

    assert "Ancestor" not in text
    assert "ancestor" not in text


def test_templates_no_longer_define_ancestor() -> None:
    hits: list[str] = []
    for path in (_REPO / "core" / "templates").rglob("*.toml"):
        text = path.read_text(encoding="utf-8")
        if "ancestor" in text or "Ancestor" in text:
            hits.append(str(path.relative_to(_REPO)))

    assert hits == []
