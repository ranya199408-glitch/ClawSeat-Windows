from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import agent_admin_window
import projects_registry


SCRIPT = Path(__file__).resolve().parents[1] / "core" / "scripts" / "projects_registry.py"


def _read_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_register_creates_file_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    created = projects_registry.register_project("alpha", "memory")

    path = tmp_path / ".clawseat" / "projects.json"
    assert created.name == "alpha"
    assert path.exists()
    assert _read_registry(path)["projects"][0]["name"] == "alpha"
    assert _read_registry(path)["projects"][0]["tmux_name"] == "alpha-memory"


def test_register_idempotent_on_duplicate_name(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    first = projects_registry.register_project("alpha", "memory")
    second = projects_registry.register_project("alpha", "memory")

    projects = _read_registry(tmp_path / ".clawseat" / "projects.json")["projects"]
    assert first.name == "alpha"
    assert second.name == "alpha"
    assert [project["name"] for project in projects] == ["alpha"]


def test_register_appends_to_existing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    projects_registry.register_project("alpha", "memory")
    projects_registry.register_project("beta", "memory", tmux_name="beta-custom")

    projects = _read_registry(tmp_path / ".clawseat" / "projects.json")["projects"]
    assert [project["name"] for project in projects] == ["alpha", "beta"]
    assert projects[1]["tmux_name"] == "beta-custom"


def test_register_atomic_write_via_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    original_replace = projects_registry.os.replace
    calls: list[tuple[Path, Path, str]] = []

    def tracking_replace(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        calls.append((src_path, dst_path, src_path.read_text(encoding="utf-8")))
        assert src_path.name.startswith("projects.")
        assert src_path.name.endswith(".json")
        assert src_path.exists()
        original_replace(src, dst)

    monkeypatch.setattr(projects_registry.os, "replace", tracking_replace)

    projects_registry.register_project("alpha", "memory")

    assert len(calls) == 1
    assert calls[0][1] == tmp_path / ".clawseat" / "projects.json"
    assert '"alpha"' in calls[0][2]


def test_register_uses_0600_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    projects_registry.register_project("alpha", "memory")

    mode = stat.S_IMODE((tmp_path / ".clawseat" / "projects.json").stat().st_mode)
    assert mode == 0o600


def test_unregister_removes_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    projects_registry.register_project("alpha", "memory")
    assert projects_registry.unregister_project("alpha") is True

    assert _read_registry(tmp_path / ".clawseat" / "projects.json")["projects"] == []


def test_unregister_returns_false_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert projects_registry.unregister_project("missing") is False
    assert _read_registry(tmp_path / ".clawseat" / "projects.json") == {
        "version": 2,
        "projects": [],
    }


def test_enumerate_returns_empty_when_registry_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert projects_registry.enumerate_projects() == []


def test_enumerate_returns_registered_projects(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))

    projects_registry.register_project("alpha", "memory")
    entries = projects_registry.enumerate_projects()

    assert len(entries) == 1
    assert entries[0].name == "alpha"
    assert entries[0].primary_seat == "memory"
    assert entries[0].tmux_name == "alpha-memory"
    assert entries[0].status == "active"


def test_corrupt_registry_treated_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    path = tmp_path / ".clawseat" / "projects.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    assert projects_registry.load_registry() == {"version": 2, "projects": []}
    assert projects_registry.enumerate_projects() == []


def test_cli_register_subcommand_exit_zero(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "register", "alpha", "--primary-seat", "memory"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["name"] == "alpha"
    assert _read_registry(tmp_path / ".clawseat" / "projects.json")["projects"][0]["name"] == "alpha"


def test_cli_register_is_idempotent(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}

    first = subprocess.run(
        [sys.executable, str(SCRIPT), "register", "alpha", "--primary-seat", "memory"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    second = subprocess.run(
        [sys.executable, str(SCRIPT), "register", "alpha", "--primary-seat", "memory"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert json.loads(first.stdout)["name"] == "alpha"
    assert second.returncode == 0
    assert json.loads(second.stdout)["name"] == "alpha"
    assert len(_read_registry(tmp_path / ".clawseat" / "projects.json")["projects"]) == 1


def test_cli_invalid_subcommand_exit_nonzero(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "bogus"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode != 0


def test_cli_list_outputs_registered_projects(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    subprocess.run(
        [sys.executable, str(SCRIPT), "register", "alpha", "--primary-seat", "memory"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "list", "--json"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)[0]["name"] == "alpha"


def test_build_memories_payload_prefers_projects_json(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_registry.register_project("alpha", "memory")
    monkeypatch.setattr(
        agent_admin_window,
        "_tmux_session_names",
        lambda: ["ghost-memory", "alpha-memory"],
    )

    payload = agent_admin_window.build_memories_payload(SimpleNamespace(name="ignored"))

    assert payload is not None
    assert payload["tabs"] == [
        {"name": "alpha", "command": "tmux attach -t '=alpha-memory'"}
    ]


def test_build_memories_payload_falls_back_to_tmux_when_registry_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        agent_admin_window,
        "_tmux_session_names",
        lambda: ["alpha-memory", "machine-memory-claude", "beta-planner"],
    )

    payload = agent_admin_window.build_memories_payload(SimpleNamespace(name="ignored"))

    assert payload is not None
    assert payload["tabs"] == [
        {"name": "alpha", "command": "tmux attach -t '=alpha-memory'"}
    ]
