"""Regression tests for the CI-aware tolerance in `skill_manager.py check`.

Companion to test_scan_project_smoke_gating: the `Skill registry check`
step of CI also hard-failed because the registry declares `gstack-*`
skills as `required=true` + `source="gstack"`, and the CI runner has no
gstack install. Without a tolerance hook the Skill step is always red on
CI, which masks genuine skill-registry breakage.

Policy:
- bundled skills missing on any host → hard fail (rc=1) always
- external skills missing on maintainer box → hard fail (rc=1)
- external skills missing on CI (CI=true or CLAWSEAT_SKIP_EXTERNAL_SKILL_CHECK=1)
  → soft (rc=2) with a stderr warning
- everything present → rc=0
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_SCRIPTS = _REPO / "core" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_CORE = _REPO / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))


def _make_item(*, name: str, source: str, exists: bool, required: bool):
    from skill_registry import SkillCheckItem

    return SkillCheckItem(
        name=name,
        source=source,
        expanded_path=f"/fake/{name}",
        exists=exists,
        required=required,
        message="",
        fix_hint="install" if not exists else "",
    )


def _make_result(items):
    from skill_registry import SkillCheckResult

    return SkillCheckResult(items=list(items))


@pytest.fixture
def args_ns():
    return SimpleNamespace(role=None, source=None, json=False)


def _run(result, args, ci: bool = False, skip_env: bool = False):
    import skill_manager

    env = {}
    if ci:
        env["CI"] = "true"
    if skip_env:
        env["CLAWSEAT_SKIP_EXTERNAL_SKILL_CHECK"] = "1"
    with patch.dict(os.environ, env, clear=False), patch(
        "skill_manager.validate_all", return_value=result
    ):
        # Drop any stale CI flag from the caller's environment when not set here.
        if not ci:
            os.environ.pop("CI", None)
        if not skip_env:
            os.environ.pop("CLAWSEAT_SKIP_EXTERNAL_SKILL_CHECK", None)
        return skill_manager.cmd_check(args)


def test_all_present_returns_zero(args_ns):
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=True, required=True),
            _make_item(name="gstack-investigate", source="gstack", exists=True, required=True),
        ]
    )
    assert _run(result, args_ns) == 0


def test_bundled_missing_hard_fails_everywhere(args_ns):
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=False, required=True),
        ]
    )
    # Bundled missing = hard fail regardless of environment.
    assert _run(result, args_ns) == 1
    assert _run(result, args_ns, ci=True) == 1
    assert _run(result, args_ns, skip_env=True) == 1


def test_external_missing_hard_fails_on_maintainer_box(args_ns):
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=True, required=True),
            _make_item(name="gstack-investigate", source="gstack", exists=False, required=True),
        ]
    )
    assert _run(result, args_ns, ci=False, skip_env=False) == 1


def test_external_missing_tolerated_on_ci(args_ns, capsys):
    """In CI mode, external-only missing returns rc=0 (warning to stderr).
    The ci.yml step treats any non-zero as failure — rc=2 would still be
    red. Tolerance means "present enough", not "optional missing"."""
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=True, required=True),
            _make_item(name="gstack-investigate", source="gstack", exists=False, required=True),
            _make_item(name="gstack-ship", source="gstack", exists=False, required=True),
        ]
    )
    rc = _run(result, args_ns, ci=True)
    assert rc == 0
    captured = capsys.readouterr()
    assert "CI tolerance" in captured.err
    assert "external required skill(s) missing" in captured.err


def test_external_missing_tolerated_with_explicit_opt_out(args_ns):
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=True, required=True),
            _make_item(name="gstack-investigate", source="gstack", exists=False, required=True),
        ]
    )
    assert _run(result, args_ns, skip_env=True) == 0


def test_optional_missing_returns_two(args_ns):
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=True, required=True),
            _make_item(name="gstack-careful", source="gstack", exists=False, required=False),
        ]
    )
    assert _run(result, args_ns) == 2


def test_ci_with_both_bundled_and_external_missing_still_hard_fails(args_ns):
    """The tolerance only kicks in when bundled skills are all present —
    never when a genuinely bundled skill is missing, even on CI."""
    result = _make_result(
        [
            _make_item(name="gstack-harness", source="bundled", exists=False, required=True),
            _make_item(name="gstack-investigate", source="gstack", exists=False, required=True),
        ]
    )
    assert _run(result, args_ns, ci=True) == 1
