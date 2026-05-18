from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "skills" / "memory-oracle" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import scan_environment as se


def test_scan_openclaw_prefers_env_override(monkeypatch, tmp_path):
    openclaw_home = tmp_path / "env-openclaw"
    monkeypatch.setenv("OPENCLAW_HOME", str(openclaw_home))
    monkeypatch.setattr(
        se.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("CLI should not run")),
    )

    result = se.scan_openclaw()

    assert result["home"] == str(openclaw_home)
    assert result["exists"] is False
    assert result["agents"] == []


def test_scan_openclaw_cli_missing_falls_back_to_home(monkeypatch, tmp_path):
    fake_home = tmp_path / "real-home"
    monkeypatch.delenv("OPENCLAW_HOME", raising=False)
    monkeypatch.setattr(se, "HOME", fake_home)
    monkeypatch.setattr(
        se.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("openclaw")),
    )

    result = se.scan_openclaw()

    assert result["home"] == str(fake_home / ".openclaw")
    assert result["exists"] is False
    assert result["agents"] == []


def test_scan_openclaw_discovers_home_from_cli(monkeypatch, tmp_path):
    fake_home = tmp_path / "real-home"
    discovered_home = fake_home / ".oc-alt"
    monkeypatch.delenv("OPENCLAW_HOME", raising=False)
    monkeypatch.setattr(se, "HOME", fake_home)
    discovered_home.mkdir(parents=True)
    monkeypatch.setattr(
        se.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="~/.oc-alt/openclaw.json\n"),
    )

    result = se.scan_openclaw()

    assert result["home"] == str(discovered_home)
    assert result["exists"] is True


def test_scan_openclaw_lists_workspace_agents(monkeypatch, tmp_path):
    openclaw_home = tmp_path / "openclaw"
    monkeypatch.setenv("OPENCLAW_HOME", str(openclaw_home))
    openclaw_home.mkdir()
    (openclaw_home / "workspace-a").mkdir()
    (openclaw_home / "workspace-a" / "WORKSPACE_CONTRACT.toml").write_text("a=1\n", encoding="utf-8")
    (openclaw_home / "workspace-b").mkdir()
    (openclaw_home / "plain-with-contract").mkdir()
    (openclaw_home / "plain-with-contract" / "WORKSPACE_CONTRACT.toml").write_text("b=2\n", encoding="utf-8")
    (openclaw_home / "plain-without-contract").mkdir()
    (openclaw_home / "not-a-dir").write_text("x", encoding="utf-8")

    result = se.scan_openclaw()

    assert result["agents"] == [
        {
            "name": "plain-with-contract",
            "workspace": str(openclaw_home / "plain-with-contract"),
            "has_contract": True,
            "project": "",
            "feishu_group_id": "",
        },
        {
            "name": "a",
            "workspace": str(openclaw_home / "workspace-a"),
            "has_contract": True,
            "project": "",
            "feishu_group_id": "",
        },
        {
            "name": "b",
            "workspace": str(openclaw_home / "workspace-b"),
            "has_contract": False,
            "project": "",
            "feishu_group_id": "",
        },
    ]


def test_scan_openclaw_empty_agents_list(monkeypatch, tmp_path):
    openclaw_home = tmp_path / "empty-openclaw"
    monkeypatch.setenv("OPENCLAW_HOME", str(openclaw_home))
    openclaw_home.mkdir()

    result = se.scan_openclaw()

    assert result["exists"] is True
    assert result["agents"] == []
