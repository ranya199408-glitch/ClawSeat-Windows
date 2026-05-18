from __future__ import annotations

import re
from pathlib import Path


EN_DOC = Path("docs/INSTALL.md")
ZH_DOC = Path("docs/INSTALL.zh-CN.md")
README = Path("README.md")
INSTALL_SCRIPT_PATHS = [Path("scripts/install.sh"), *Path("scripts/install/lib").glob("*.sh")]

REQUIRED_FLAGS = [
    "--template",
    "--provider",
    "--force-repo-root",
    "--all-api-provider",
    "--reset-harness-memory",
    "--memory-tool",
    "--memory-model",
    "--load-all-skills",
    "--enable-auto-patrol",
    "--base-url",
    "--api-key",
]

REQUIRED_ZH_KEYWORDS = [
    "Provider",
    "Non-TTY",
    "Trust",
    "capture-pane",
    "sandbox",
    "worktree",
    "NON_TTY_NO_PROVIDER",
    "NON_TTY_NO_TEMPLATE",
]


def _install_error_codes() -> set[str]:
    codes: set[str] = set()
    pattern = re.compile(r"\bdie\s+\d+\s+([A-Z0-9_]+)")
    for path in INSTALL_SCRIPT_PATHS:
        codes.update(pattern.findall(path.read_text(encoding="utf-8")))
    return codes


def test_zh_cn_doc_exists_and_has_lang_links() -> None:
    """docs/INSTALL.zh-CN.md exists and both install docs expose language links."""
    assert ZH_DOC.exists(), "docs/INSTALL.zh-CN.md missing"
    zh = ZH_DOC.read_text(encoding="utf-8")
    en = EN_DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    assert "INSTALL.md" in zh, "zh-CN doc must link back to English version"
    assert "INSTALL.zh-CN.md" in en, "English install doc must link to zh-CN"
    assert "docs/INSTALL.zh-CN.md" in readme, "README must link to zh-CN install doc"


def test_zh_cn_doc_covers_key_flags_and_z_sections() -> None:
    """Critical flags and AA/Z/V sections appear in both install docs."""
    en = EN_DOC.read_text(encoding="utf-8")
    zh = ZH_DOC.read_text(encoding="utf-8")
    zh_lower = zh.lower()
    for flag in REQUIRED_FLAGS:
        assert flag in en, f"EN doc missing flag: {flag}"
        assert flag in zh, f"ZH doc missing flag: {flag}"
    for keyword in REQUIRED_ZH_KEYWORDS:
        assert keyword.lower() in zh_lower, f"ZH doc missing section keyword: {keyword}"


def test_zh_cn_doc_lists_all_install_error_codes() -> None:
    """Every install-script die code appears in the Chinese install guide."""
    zh = ZH_DOC.read_text(encoding="utf-8")
    missing = sorted(code for code in _install_error_codes() if code not in zh)
    assert not missing, f"docs/INSTALL.zh-CN.md missing install error codes: {missing}"
