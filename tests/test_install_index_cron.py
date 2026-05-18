from __future__ import annotations

import importlib.util
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_INSTALLER = _REPO / "core" / "skills" / "memory-oracle" / "scripts" / "install_index_cron.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location("install_index_cron", _INSTALLER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_remove_entry_preserves_unrelated_crontab_lines() -> None:
    installer = _load_installer()
    existing = "\n".join(
        [
            "MAILTO=ops@example.com",
            installer.MARKER,
            f"0 3 * * * {installer.CRON_SCRIPT}",
            "SHELL=/bin/bash",
            "",
        ]
    )

    cleaned = installer._remove_entry(existing)

    assert installer.MARKER not in cleaned
    assert str(installer.CRON_SCRIPT) not in cleaned
    assert "MAILTO=ops@example.com" in cleaned
    assert "SHELL=/bin/bash" in cleaned


def test_install_and_uninstall_roundtrip(monkeypatch) -> None:
    installer = _load_installer()
    writes: list[str] = []
    monkeypatch.setattr(installer, "_current_crontab", lambda: "MAILTO=ops@example.com\n")
    monkeypatch.setattr(installer, "_write_crontab", writes.append)

    installer.install()
    assert installer.MARKER in writes[0]
    assert str(installer.CRON_SCRIPT) in writes[0]

    monkeypatch.setattr(installer, "_current_crontab", lambda: writes[0])
    installer.uninstall()
    assert installer.MARKER not in writes[1]
    assert str(installer.CRON_SCRIPT) not in writes[1]
