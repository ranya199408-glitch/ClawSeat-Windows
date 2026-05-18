from __future__ import annotations

import importlib.util
from pathlib import Path


_SETUP_HELPERS = Path(__file__).with_name("test_install_privacy_setup.py")
_setup_spec = importlib.util.spec_from_file_location("_v_install_privacy_setup", _SETUP_HELPERS)
assert _setup_spec is not None
assert _setup_spec.loader is not None
_setup = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(_setup)

_prepare_fake_root = _setup._prepare_h3_fake_root
_run_install = _setup._run_install


def test_clawseat_skills_visible_to_all_tool_homes(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_fake_root(tmp_path)
    result = _run_install(root, home, py_stubs, project="all-tools-visible")
    assert result.returncode == 0, result.stderr

    agents_skills = home / ".agents" / "skills"
    agents_names = {path.name for path in agents_skills.iterdir()}

    assert agents_names
    for tool in ("claude", "codex"):
        tool_names = {path.name for path in (home / f".{tool}" / "skills").iterdir()}
        assert tool_names >= agents_names
    gemini_skills = home / ".gemini" / "skills"
    assert not gemini_skills.exists() or not ({path.name for path in gemini_skills.iterdir()} & agents_names)
