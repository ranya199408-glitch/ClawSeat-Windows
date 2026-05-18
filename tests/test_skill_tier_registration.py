from __future__ import annotations

import os
import importlib.util
from pathlib import Path


_SETUP_HELPERS = Path(__file__).with_name("test_install_privacy_setup.py")
_setup_spec = importlib.util.spec_from_file_location("_t3_install_privacy_setup", _SETUP_HELPERS)
assert _setup_spec is not None
assert _setup_spec.loader is not None
_setup = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(_setup)

_prepare_h3_fake_root = _setup._prepare_h3_fake_root
_run_install = _setup._run_install

_CORE_SKILLS = ("clawseat-memory", "clawseat-decision-escalation")
_EXTENDED_SKILLS = ("clawseat-koder", "clawseat-privacy", "clawseat-memory-reporting", "openclaw-feishu")


def _assert_skill_links(root: Path, skills_home: Path, skills: tuple[str, ...]) -> None:
    for skill in skills:
        link = skills_home / skill
        assert link.is_symlink()
        assert os.readlink(link) == str(root / "core" / "skills" / skill)


def _assert_tool_mirror_links(home: Path, skills_home: Path, skills: tuple[str, ...]) -> None:
    for skill in skills:
        link = skills_home / skill
        assert link.is_symlink()
        assert os.readlink(link) == str(home / ".agents" / "skills" / skill)


def test_codex_tier_registration_mirrors_agents_ssot(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    result = _run_install(root, home, py_stubs, project="t3codex", memory_tool="codex")
    assert result.returncode == 0, result.stderr

    _assert_skill_links(root, home / ".agents" / "skills", (*_CORE_SKILLS, *_EXTENDED_SKILLS))
    skills_home = home / ".codex" / "skills"
    _assert_tool_mirror_links(home, skills_home, (*_CORE_SKILLS, *_EXTENDED_SKILLS))
    assert "Extended skills skipped" not in result.stdout


def test_codex_tier_registration_removes_stale_extended_links(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    skills_home = home / ".codex" / "skills"
    skills_home.mkdir(parents=True)
    for skill in _EXTENDED_SKILLS:
        (skills_home / skill).symlink_to(root / "core" / "skills" / skill)

    result = _run_install(root, home, py_stubs, project="t3stale", memory_tool="codex")
    assert result.returncode == 0, result.stderr

    _assert_tool_mirror_links(home, skills_home, (*_CORE_SKILLS, *_EXTENDED_SKILLS))


def test_claude_tier_registration_core_and_extended(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    result = _run_install(root, home, py_stubs, project="t3claude", memory_tool="claude")
    assert result.returncode == 0, result.stderr

    skills_home = home / ".agents" / "skills"
    _assert_skill_links(root, skills_home, (*_CORE_SKILLS, *_EXTENDED_SKILLS))
    _assert_tool_mirror_links(home, home / ".claude" / "skills", (*_CORE_SKILLS, *_EXTENDED_SKILLS))
    assert "Extended skills skipped" not in result.stdout


def test_gemini_tier_registration_uses_agents_alias_without_mirror(tmp_path: Path) -> None:
    root, home, py_stubs = _prepare_h3_fake_root(tmp_path)
    result = _run_install(root, home, py_stubs, project="t3gemini", memory_tool="gemini")
    assert result.returncode == 0, result.stderr

    _assert_skill_links(root, home / ".agents" / "skills", (*_CORE_SKILLS, *_EXTENDED_SKILLS))
    skills_home = home / ".gemini" / "skills"
    for skill in (*_CORE_SKILLS, *_EXTENDED_SKILLS):
        assert not (skills_home / skill).exists()
    assert "Extended skills skipped" not in result.stdout
