from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "core" / "scripts"


def _load_agent_admin(home: Path):
    os.environ["CLAWSEAT_REAL_HOME"] = str(home)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    for name in [n for n in list(sys.modules) if n.startswith("agent_admin") or n == "real_home"]:
        sys.modules.pop(name, None)
    return importlib.import_module("agent_admin")


def _write_project_toml(project_dir: Path, *, name: str, includes_declared: bool) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    text = [
        'version = 1',
        f'name = "{name}"',
        'repo_root = "/tmp/repo"',
        'monitor_session = "project-cartooner-monitor"',
        'engineers = ["memory", "writer", "visual", "patrol"]',
        'monitor_engineers = ["memory", "writer", "visual", "patrol"]',
        'window_mode = "split-2"',
        'monitor_max_panes = 4',
        'open_detail_windows = false',
    ]
    if includes_declared:
        text.extend(
            [
                'declared_skills = [',
                '  "cartooner-image",',
                '  "cartooner-video",',
                '  "cartooner-audio"',
                ']',
            ]
        )
    project_dir.joinpath("project.toml").write_text("\n".join(text) + "\n", encoding="utf-8")


def test_declared_skills_roundtrip_via_project_toml(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_dir = home / ".agents" / "projects" / "cartooner"
    _write_project_toml(project_dir, name="cartooner", includes_declared=True)

    aa = _load_agent_admin(home)
    project = aa.load_project("cartooner")
    assert hasattr(project, "declared_skills")
    assert project.declared_skills == ["cartooner-image", "cartooner-video", "cartooner-audio"]

    project.declared_skills.append("cartooner-prompt")
    aa.write_project(project)

    saved = tomllib.loads(project_dir.joinpath("project.toml").read_text(encoding="utf-8"))
    assert saved["declared_skills"] == [
        "cartooner-image",
        "cartooner-video",
        "cartooner-audio",
        "cartooner-prompt",
    ]


def test_declared_skills_absent_for_other_project_is_non_blocking(tmp_path: Path) -> None:
    home = tmp_path / "home"
    legacy_dir = home / ".agents" / "projects" / "legacy"
    _write_project_toml(legacy_dir, name="legacy", includes_declared=False)

    aa = _load_agent_admin(home)
    project = aa.load_project("legacy")
    assert hasattr(project, "declared_skills"), "declared_skills must be present as a soft field"
    assert project.declared_skills == []

    raw = legacy_dir.joinpath("project.toml").read_text(encoding="utf-8")
    restored = tomllib.loads(raw)
    assert "declared_skills" not in restored
    assert "engineers" in restored
