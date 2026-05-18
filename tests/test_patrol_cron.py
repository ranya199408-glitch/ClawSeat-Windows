from __future__ import annotations

import importlib.util
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_INSTALLER = _REPO / "core" / "skills" / "patrol" / "scripts" / "install_patrol_cron.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location("install_patrol_cron", _INSTALLER)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cron_install_adds_entries(monkeypatch) -> None:
    installer = _load_installer()
    written: list[str] = []
    monkeypatch.setattr(installer, "_current_crontab", lambda: "MAILTO=ops@example.com\n")
    monkeypatch.setattr(installer, "_write_crontab", written.append)

    installer.install()

    assert installer.MARKER in written[0]
    assert "0 3 * * *" in written[0]
    assert "0 3 * * 0" in written[0]
    assert "patrol_cron.sh daily" in written[0]
    assert "patrol_cron.sh weekly" in written[0]


def test_cron_uninstall_removes_entries(monkeypatch) -> None:
    installer = _load_installer()
    existing = "\n".join([
        "MAILTO=ops@example.com",
        installer.MARKER,
        f"0 3 * * * {installer.SCRIPT} daily",
        f"0 3 * * 0 {installer.SCRIPT} weekly",
        "",
    ])
    written: list[str] = []
    monkeypatch.setattr(installer, "_current_crontab", lambda: existing)
    monkeypatch.setattr(installer, "_write_crontab", written.append)

    installer.uninstall()

    assert installer.MARKER not in written[0]
    assert "patrol_cron.sh" not in written[0]
    assert "MAILTO=ops@example.com" in written[0]
