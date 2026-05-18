from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock


_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_project_create_prints_install_sh_hint(tmp_path: Path, monkeypatch, capsys) -> None:
    import agent_admin_crud

    monkeypatch.setattr(agent_admin_crud, "HOME", tmp_path)
    hooks = MagicMock()
    hooks.normalize_name.side_effect = lambda value: value
    hooks.project_path.return_value = tmp_path / ".agents" / "projects" / "demo" / "project.toml"
    hooks.load_template.return_value = {
        "template_name": "clawseat-creative",
        "engineers": [],
        "window_mode": "tabs-2up",
        "monitor_max_panes": 0,
        "open_detail_windows": False,
    }
    hooks.merge_template_local.return_value = {
        "repo_root": str(tmp_path / "repo"),
        "engineers": [],
        "window_mode": "tabs-2up",
        "monitor_max_panes": 0,
        "open_detail_windows": False,
    }
    hooks.project_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
    hooks.write_text.side_effect = lambda path, content, mode=None: (
        Path(path).parent.mkdir(parents=True, exist_ok=True),
        Path(path).write_text(content, encoding="utf-8"),
    )
    handlers = agent_admin_crud.CrudHandlers(hooks)

    rc = handlers.project_create(
        SimpleNamespace(project="demo", repo_root=str(tmp_path / "repo"), template="clawseat-creative", window_mode=None, open_detail_windows=False)
    )

    assert rc == 0
    stderr = capsys.readouterr().err
    assert "install.sh" in stderr
    assert "canonical" in stderr


def test_memory_skill_has_install_canonicality_section() -> None:
    text = (_REPO / "core" / "skills" / "memory-oracle" / "SKILL.md").read_text(encoding="utf-8")

    assert "Install Flow Canonicality" in text
    assert "install.sh is the canonical entry point" in text
    assert "agent_admin project create" in text
    assert "workspace rendering, profile generation, secret seeding, and skills installation" in text
