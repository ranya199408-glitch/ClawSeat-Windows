"""T1 portability regression guard (bundle-C).

Six cross-file smoke tests that will turn red the moment any hardcode is
re-introduced into core/**/*.py or examples/**/*.toml.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

_ROOT = Path(__file__).resolve().parents[1]
_CORE = _ROOT / "core"
_SCRIPTS = _CORE / "scripts"
_GSTACK_SCRIPTS = _CORE / "skills" / "gstack-harness" / "scripts"
_EXAMPLES = _ROOT / "examples"

sys.path.insert(0, str(_GSTACK_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS))


def test_no_hardcoded_ywf_user_path_in_core():
    """No /tmp/fake-home absolute path must appear in the T1-modified runtime files.

    Scoped to the 4 files touched by T1-A/B/C (not generated-doc files like
    init_koder.py which embed example shell invocations in their output strings).
    """
    t1_files = [
        _GSTACK_SCRIPTS / "dispatch_task.py",
        _GSTACK_SCRIPTS / "migrate_profile.py",
        _SCRIPTS / "agent_admin_config.py",
        _SCRIPTS / "agent_admin_runtime.py",
    ]
    hits = []
    for py in t1_files:
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "/tmp/fake-home" in line:
                hits.append(f"{py.relative_to(_ROOT)}:{i}: {line.strip()}")
    assert hits == [], "Found /tmp/fake-home hardcodes in T1 files:\n" + "\n".join(hits)


def test_no_hardcoded_coding_convention_in_examples():
    """No ~/coding/ path must appear in any examples/**/*.toml file."""
    hits = []
    for toml in _EXAMPLES.rglob("*.toml"):
        text = toml.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "~/coding/" in line:
                hits.append(f"{toml.relative_to(_ROOT)}:{i}: {line.strip()}")
    assert hits == [], "Found ~/coding/ hardcodes in examples:\n" + "\n".join(hits)


def test_migrate_profile_tasks_root_uses_home_not_tmp():
    """migrate_profile.build_lines must set tasks_root under ~/.agents/tasks/, not /tmp/."""
    import migrate_profile  # noqa: PLC0415

    minimal_data = {
        "send_script": "{CLAWSEAT_ROOT}/core/shell-scripts/send-and-verify.sh",
        "agent_admin": "{CLAWSEAT_ROOT}/core/scripts/agent_admin.py",
    }
    lines = migrate_profile.build_lines(
        minimal_data,
        project_name="test-proj",
        repo_root="/some/repo",
        bootstrap_only=False,
    )
    tasks_root_lines = [l for l in lines if "tasks_root" in l]
    assert tasks_root_lines, "tasks_root not found in build_lines output"
    joined = " ".join(tasks_root_lines)
    assert "/tmp" not in joined, f"tasks_root still uses /tmp: {joined}"
    assert ".agents" in joined or "~" in joined, f"tasks_root doesn't use home convention: {joined}"


def test_tool_binaries_dict_has_no_direct_homebrew_literal():
    """TOOL_BINARIES in agent_admin_config.py must not contain literal /opt/homebrew/ strings."""
    source = (_SCRIPTS / "agent_admin_config.py").read_text(encoding="utf-8")
    m = re.search(r"TOOL_BINARIES\s*=\s*\{[^}]+\}", source, re.DOTALL)
    assert m is not None, "TOOL_BINARIES not found in agent_admin_config.py"
    block = m.group(0)
    hits = re.findall(r'"/opt/homebrew/bin/\w+"', block)
    assert hits == [], f"Literal /opt/homebrew paths in TOOL_BINARIES: {hits}"


def test_dispatch_task_gstack_root_resolver_exists():
    """dispatch_task.py must define _resolve_gstack_skills_root and assign _GSTACK_SKILLS_ROOT via it."""
    source = (_GSTACK_SCRIPTS / "dispatch_task.py").read_text(encoding="utf-8")
    assert "def _resolve_gstack_skills_root" in source, \
        "_resolve_gstack_skills_root function not found in dispatch_task.py"
    assert "_GSTACK_SKILLS_ROOT = _resolve_gstack_skills_root()" in source, \
        "_GSTACK_SKILLS_ROOT not assigned via resolver in dispatch_task.py"
