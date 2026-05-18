from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def test_install_dynamic_profile_runtime_paths_exist() -> None:
    profile = Path.home() / ".agents" / "profiles" / "install-profile-dynamic.toml"
    assert profile.is_file()

    data = tomllib.loads(profile.read_text(encoding="utf-8"))
    expected = {
        "tasks_root": Path.home() / ".agents" / "tasks" / "install",
        "workspace_root": Path.home() / ".agents" / "workspaces" / "install",
        "handoff_dir": Path.home() / ".agents" / "tasks" / "install" / "patrol" / "handoffs",
    }

    for key, expected_path in expected.items():
        raw = str(data.get(key, ""))
        assert raw, f"profile missing {key}"
        assert Path(raw).expanduser() == expected_path
        assert expected_path.is_dir(), f"{key} path does not exist: {expected_path}"
