from __future__ import annotations

import importlib.util
import os
from pathlib import Path

_SETUP_HELPERS = Path(__file__).with_name("test_install_privacy_setup.py")
_setup_spec = importlib.util.spec_from_file_location("_ac_install_privacy_setup", _SETUP_HELPERS)
assert _setup_spec is not None
assert _setup_spec.loader is not None
_setup = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(_setup)

_prepare_h3_fake_root = _setup._prepare_h3_fake_root
_run_install = _setup._run_install


def test_install_skips_gemini_skill_symlinks_and_cleans_legacy_links(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    gemini_skills = home / ".gemini" / "skills"
    gemini_skills.mkdir(parents=True)
    legacy = gemini_skills / "clawseat-memory"
    unmanaged = gemini_skills / "operator-owned"
    unmanaged_target = home / "operator-owned-skill"
    unmanaged_target.mkdir()
    legacy.symlink_to(home / ".agents" / "skills" / "clawseat-memory")
    unmanaged.symlink_to(unmanaged_target)

    result = _run_install(root, home, py_stubs, project="acskills")
    assert result.returncode == 0, result.stderr

    assert not legacy.exists()
    assert unmanaged.is_symlink()
    assert os.readlink(unmanaged) == str(unmanaged_target)

    for tool in ("claude", "codex"):
        link = home / f".{tool}" / "skills" / "clawseat-memory"
        assert link.is_symlink()
        assert os.readlink(link) == str(home / ".agents" / "skills" / "clawseat-memory")

    for skill in ("clawseat-memory", "clawseat-decision-escalation"):
        assert not (gemini_skills / skill).exists()
