from __future__ import annotations

from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


def test_install_docs_cover_dispatch_task_profile_troubleshooting() -> None:
    english = (_REPO / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    chinese = (_REPO / "docs" / "INSTALL.zh-CN.md").read_text(encoding="utf-8")

    for text in (english, chinese):
        assert "dispatch_task.py" in text
        assert "FileNotFoundError" in text
        assert "profile-dynamic.toml" in text
        assert "install.sh --project <project> --reinstall" in text
