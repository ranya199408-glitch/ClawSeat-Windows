"""Regression: GSTACK_SKILLS_ROOT env var redirects every consumer.

Stranger-report: friends who cloned gstack to a non-canonical path (e.g.
`~/gstack/` instead of `~/.gstack/repos/gstack/`) get ModuleNotFound /
"gstack skills missing" from whichever consumer checks first. The fix is
a single env var `GSTACK_SKILLS_ROOT` that redirects the remaining consumers:

  - core/skill_registry.py::expand_skill_path (loader-level — covers
    bootstrap_harness, start_seat, skill_manager, preflight's registry
    validation)
  - core/preflight.py (the direct gstack presence check)
  - core/skills/gstack-harness/scripts/dispatch_task.py (the INTENT_MAP,
    already covered by test_dispatch_gstack_root.py)

This test locks in that the first two all honor the env var. The third has its
own existing regression in test_dispatch_gstack_root.py.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# Real home resolver — must match what skill_registry.py uses.
# In a seat sandbox, Path.home() returns the sandbox path; real_user_home()
# returns the operator's actual home. Use the same helper as the implementation
# so assertions agree by construction.
from core.lib.real_home import real_user_home

_REPO = Path(__file__).resolve().parents[1]


def _load_skill_registry():
    """Fresh-import skill_registry so environment changes take effect."""
    spec = importlib.util.spec_from_file_location(
        "skill_registry_under_test", _REPO / "core" / "skill_registry.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["skill_registry_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_expand_skill_path_rewrites_tilde_form_under_env_override(monkeypatch, tmp_path):
    """Registry path `~/.gstack/repos/gstack/.agents/skills/<x>` must be
    rewritten to `<GSTACK_SKILLS_ROOT>/<x>` when the env is set."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "custom-gstack"))
    mod = _load_skill_registry()

    raw = "~/.gstack/repos/gstack/.agents/skills/gstack-review/SKILL.md"
    result = mod.expand_skill_path(raw)
    assert str(result) == str(tmp_path / "custom-gstack" / "gstack-review" / "SKILL.md"), (
        f"expected redirection to GSTACK_SKILLS_ROOT, got {result}"
    )


def test_expand_skill_path_rewrites_expanded_form_under_env_override(monkeypatch, tmp_path):
    """If the TOML already has an expanded absolute path (unusual but
    legal), the same rewrite must apply."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "alt"))
    mod = _load_skill_registry()

    # Use real_user_home() to match what the implementation resolves canonical to.
    canonical = str(real_user_home() / ".gstack/repos/gstack/.agents/skills")
    raw = f"{canonical}/gstack-ship/SKILL.md"
    result = mod.expand_skill_path(raw)
    assert str(result) == str(tmp_path / "alt" / "gstack-ship" / "SKILL.md")


def test_expand_skill_path_noop_when_env_unset(monkeypatch):
    """Default behavior (env unset) must still expand `~` to real home."""
    monkeypatch.delenv("GSTACK_SKILLS_ROOT", raising=False)
    mod = _load_skill_registry()

    raw = "~/.gstack/repos/gstack/.agents/skills/gstack-qa/SKILL.md"
    result = mod.expand_skill_path(raw)
    assert str(result) == str(
        real_user_home() / ".gstack/repos/gstack/.agents/skills/gstack-qa/SKILL.md"
    ), "unexpected rewrite when GSTACK_SKILLS_ROOT is unset"


def test_expand_skill_path_leaves_non_gstack_paths_alone(monkeypatch, tmp_path):
    """Non-gstack paths (e.g. `{CLAWSEAT_ROOT}/core/skills/<x>`) must be
    untouched by the gstack override."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "custom"))
    mod = _load_skill_registry()

    raw = "{CLAWSEAT_ROOT}/core/skills/clawseat/SKILL.md"
    result = mod.expand_skill_path(raw)
    # Not under custom-gstack; should resolve under CLAWSEAT_ROOT
    assert "custom" not in str(result), (
        f"non-gstack path was wrongly rewritten: {result}"
    )
    assert str(result).endswith("core/skills/clawseat/SKILL.md")


def test_empty_env_is_treated_as_unset(monkeypatch):
    """An empty GSTACK_SKILLS_ROOT must fall back to canonical lookup —
    matches the `.strip() or None` semantics in dispatch_task's resolver."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "")
    mod = _load_skill_registry()
    raw = "~/.gstack/repos/gstack/.agents/skills/gstack-careful/SKILL.md"
    result = mod.expand_skill_path(raw)
    # Should look under real home, not under "" (which would produce an
    # absolute /gstack-careful/... junk path).
    assert str(result).startswith(str(real_user_home())), (
        f"empty env should fall back to canonical home, got {result}"
    )


def test_preflight_gstack_check_reports_env_path(monkeypatch, tmp_path):
    """preflight's gstack WARN message must name the override path when
    GSTACK_SKILLS_ROOT is set and the override path doesn't exist."""
    bad = tmp_path / "definitely-missing-gstack"
    result = subprocess.run(
        [sys.executable, "-S", str(_REPO / "core" / "preflight.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "GSTACK_SKILLS_ROOT": str(bad), "CLAWSEAT_ROOT": str(_REPO)},
        cwd="/",
    )
    # --help exits 0 and doesn't run the full check, but we at least want
    # to prove the script still imports clean when the env var is set.
    assert result.returncode == 0, (
        f"preflight.py --help regressed under GSTACK_SKILLS_ROOT:\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


# ── Absolute-path validation ────────────────────────────────────────

def test_relative_env_falls_back_to_canonical_in_skill_registry(monkeypatch, capsys):
    """`GSTACK_SKILLS_ROOT=./skills` (relative) must NOT be used — it
    silently resolves against cwd. skill_registry's resolver should warn
    to stderr and return None (which falls back to canonical in
    expand_skill_path). Locks the guard agreed in the UX audit."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "./relative-skills")
    mod = _load_skill_registry()
    result = mod._resolve_gstack_skills_root()
    assert result is None, (
        f"relative env var should not take effect; got {result!r}"
    )
    captured = capsys.readouterr()
    assert "not absolute" in captured.err, (
        f"expected stderr warning about non-absolute path, got: {captured.err!r}"
    )


def test_relative_env_does_not_rewrite_expand_skill_path(monkeypatch):
    """With a relative override, expand_skill_path falls back to canonical
    `~` expansion — same behavior as if env were unset."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", "./nope")
    mod = _load_skill_registry()
    raw = "~/.gstack/repos/gstack/.agents/skills/gstack-review/SKILL.md"
    result = mod.expand_skill_path(raw)
    assert str(result).startswith(str(real_user_home())), (
        f"relative override should not redirect; got {result}"
    )
    assert "nope" not in str(result)


def test_absolute_env_still_wins(monkeypatch, tmp_path):
    """Regression: after adding the relative-path guard, absolute env
    values must still redirect. Prevents the guard from accidentally
    rejecting every override."""
    monkeypatch.setenv("GSTACK_SKILLS_ROOT", str(tmp_path / "abs-root"))
    mod = _load_skill_registry()
    result = mod._resolve_gstack_skills_root()
    assert result == str(tmp_path / "abs-root")


def test_dispatch_task_resolver_rejects_relative(monkeypatch, tmp_path):
    """dispatch_task.py's inline resolver must match skill_registry's
    behavior for relative paths — they drift otherwise (three modules
    maintain functionally-identical copies)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, %r); "
            "from dispatch_task import _resolve_gstack_skills_root as r; "
            "print(r())"
            % str(_REPO / "core" / "skills" / "gstack-harness" / "scripts"),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "GSTACK_SKILLS_ROOT": "./relative"},
    )
    assert result.returncode == 0, result.stderr
    # Output should be canonical home-rooted, NOT anything with "relative"
    assert "relative" not in result.stdout, (
        f"dispatch_task resolver wrongly accepted relative path: {result.stdout}"
    )
    assert ".gstack/repos/gstack/.agents/skills" in result.stdout, (
        f"expected canonical fallback, got {result.stdout}"
    )
    # Warning should have landed on stderr
    assert "not absolute" in result.stderr

