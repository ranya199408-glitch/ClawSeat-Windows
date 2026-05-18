from __future__ import annotations

import importlib.util
import os
from pathlib import Path


_SETUP_HELPERS = Path(__file__).with_name("test_install_privacy_setup.py")
_setup_spec = importlib.util.spec_from_file_location("_bj_install_privacy_setup", _SETUP_HELPERS)
assert _setup_spec is not None and _setup_spec.loader is not None
_setup = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(_setup)

_prepare_h3_fake_root = _setup._prepare_h3_fake_root
_run_install = _setup._run_install


def _add_openclaw_bridge_skill_dirs(root: Path) -> None:
    for skill in ("clawseat-intake", "clawseat-koder"):
        skill_dir = root / "core" / "skills" / skill
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill}\n", encoding="utf-8")


def test_install_mirrors_openclaw_whitelist_when_openclaw_exists(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    _add_openclaw_bridge_skill_dirs(root)
    (home / ".openclaw").mkdir(parents=True)

    result = _run_install(root, home, py_stubs, project="bjopenclaw")
    assert result.returncode == 0, result.stderr

    openclaw_skills = home / ".openclaw" / "skills"
    for skill in ("clawseat-intake", "clawseat-koder"):
        link = openclaw_skills / skill
        assert link.is_symlink()
        assert os.readlink(link) == str(home / ".agents" / "skills" / skill)
    assert not (openclaw_skills / "clawseat-memory").exists()


def test_install_skips_openclaw_mirror_when_openclaw_absent(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    _add_openclaw_bridge_skill_dirs(root)

    result = _run_install(root, home, py_stubs, project="bjnoopenclaw")
    assert result.returncode == 0, result.stderr
    assert not (home / ".openclaw").exists()
