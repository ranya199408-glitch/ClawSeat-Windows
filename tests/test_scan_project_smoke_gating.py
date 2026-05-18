"""Regression tests for the CI-aware skip gating in
test_scan_project_smoke (fix for PR-red-CI across claude/audit-* branches).

Goal: the `_require_repo` helper must fail loudly on a maintainer box
where the repo has been deleted (SPEC §5.3.1/§5.3.2) but must skip — not
fail — on CI runners where the user-scoped paths can never exist.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


_SMOKE_MODULE_PATH = Path(__file__).resolve().parent / "test_scan_project_smoke.py"


def _load_smoke_module():
    # Deliberately NOT collected as a test module; load it as a plain
    # helper so we can poke at its private functions without triggering
    # the collection pass (which would try to read real repos).
    spec = importlib.util.spec_from_file_location(
        "scan_project_smoke_helper", _SMOKE_MODULE_PATH
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_missing_repo_in_ci_mode_skips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    smoke = _load_smoke_module()
    monkeypatch.setenv("CI", "true")
    monkeypatch.delenv("CLAWSEAT_SKIP_REAL_REPO_SMOKE", raising=False)
    with pytest.raises(pytest.skip.Exception) as info:
        smoke._require_repo(tmp_path / "does-not-exist", "test-label")
    assert "Skipped because CI" in str(info.value)
    assert "test-label" in str(info.value)


def test_missing_repo_with_explicit_opt_out_skips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smoke = _load_smoke_module()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("CLAWSEAT_SKIP_REAL_REPO_SMOKE", "1")
    with pytest.raises(pytest.skip.Exception):
        smoke._require_repo(tmp_path / "does-not-exist", "opt-out")


def test_missing_repo_on_maintainer_box_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smoke = _load_smoke_module()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CLAWSEAT_SKIP_REAL_REPO_SMOKE", raising=False)
    with pytest.raises(pytest.fail.Exception) as info:
        smoke._require_repo(tmp_path / "does-not-exist", "local-dev")
    # The message must NOT reference the skip clause — we want a
    # maintainer on a misconfigured box to see the SPEC reference.
    assert "SPEC §5.3.1/§5.3.2" in str(info.value)
    assert "Cannot silently skip" in str(info.value)


def test_existing_repo_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smoke = _load_smoke_module()
    monkeypatch.delenv("CI", raising=False)
    # The repo exists — neither skip nor fail should fire.
    smoke._require_repo(tmp_path, "sanity")


def test_ci_skip_allowed_env_flag_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    smoke = _load_smoke_module()
    cases = [
        ({"CI": "true"}, True),
        ({"CI": "TRUE"}, True),
        ({"CI": "1"}, True),
        ({"CI": "false"}, False),
        ({"CI": ""}, False),
        ({"CLAWSEAT_SKIP_REAL_REPO_SMOKE": "1"}, True),
        ({"CLAWSEAT_SKIP_REAL_REPO_SMOKE": "0"}, False),
    ]
    for env, expected in cases:
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("CLAWSEAT_SKIP_REAL_REPO_SMOKE", raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        assert smoke._ci_skip_allowed() is expected, env
