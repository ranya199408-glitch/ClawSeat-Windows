from __future__ import annotations

import re
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_INSTALL_DOC = _REPO / "docs" / "INSTALL.md"
_INSTALL_SCRIPT_PATHS = [
    _REPO / "scripts" / "install.sh",
    *_REPO.joinpath("scripts", "install", "lib").glob("*.sh"),
]
_DIE_CODE_RE = re.compile(r"\bdie\s+\d+\s+([A-Z][A-Z0-9_]+)\b")


def test_install_doc_lists_all_script_error_codes() -> None:
    """Every install-script die code appears in INSTALL.md."""
    script_codes: set[str] = set()
    for path in _INSTALL_SCRIPT_PATHS:
        script_codes.update(_DIE_CODE_RE.findall(path.read_text(encoding="utf-8")))

    install_doc = _INSTALL_DOC.read_text(encoding="utf-8")
    missing = sorted(code for code in script_codes if code not in install_doc)
    assert not missing, f"docs/INSTALL.md missing install error codes: {missing}"

    assert "ENV_SCAN_FAILED" not in install_doc
    assert "ITERM_DRIVER_FAIL:" not in install_doc
