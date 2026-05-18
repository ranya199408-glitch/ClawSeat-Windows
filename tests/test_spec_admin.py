"""Unit tests for core/scripts/spec_admin.py.

Covers the six subcommands (create/show/lock/amend/verify/close) and the
spec file layout invariants. Uses CLAWSEAT_SPEC_BASE to redirect the spec
root into a tmp directory so tests are hermetic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SPEC_ADMIN = _REPO_ROOT / "core" / "scripts" / "spec_admin.py"


def _run(*args: str, base: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(base.parent),
           "CLAWSEAT_SPEC_BASE": str(base)}
    return subprocess.run(
        [sys.executable, str(_SPEC_ADMIN), *args],
        capture_output=True, text=True, env=env,
        cwd=str(cwd or _REPO_ROOT),
        timeout=30,
    )


# ── create ────────────────────────────────────────────────────────────────────


def test_create_makes_drafting_spec(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    result = _run("create", "--project", "test", "--task-id", "TID-1",
                  "--title", "首测", base=base)
    assert result.returncode == 0, result.stderr
    spec = base / "test" / "spec" / "TID-1" / "SPEC.md"
    assert spec.exists()
    text = spec.read_text(encoding="utf-8")
    assert "spec_id: TID-1" in text
    assert "project: test" in text
    assert "status: drafting" in text
    assert "# 首测" in text
    assert (base / "test" / "spec" / "TID-1" / "amendments").is_dir()


def test_create_refuses_existing_without_force(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    result = _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    assert result.returncode != 0
    assert "already exists" in result.stderr


def test_create_force_overwrites(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "old", base=base)
    result = _run("create", "--project", "p", "--task-id", "T", "--title", "new",
                  "--force", base=base)
    assert result.returncode == 0
    spec = base / "p" / "spec" / "T" / "SPEC.md"
    assert "# new" in spec.read_text(encoding="utf-8")


# ── show ──────────────────────────────────────────────────────────────────────


def test_show_renders_summary(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "标题", base=base)
    result = _run("show", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode == 0
    assert "spec_id : T" in result.stdout
    assert "status  : drafting" in result.stdout
    assert "title   : 标题" in result.stdout
    assert "Acceptance Criteria:" in result.stdout


def test_show_missing_spec_fails(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    result = _run("show", "--project", "missing", "--task-id", "X", base=base)
    assert result.returncode != 0
    assert "not found" in result.stderr


# ── lock ──────────────────────────────────────────────────────────────────────


def test_lock_transitions_status(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    result = _run("lock", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode == 0
    spec = base / "p" / "spec" / "T" / "SPEC.md"
    assert "status: locked" in spec.read_text(encoding="utf-8")


def test_lock_rejects_closed_spec(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)
    _run("close", "--project", "p", "--task-id", "T", base=base)
    result = _run("lock", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode != 0


# ── amend ─────────────────────────────────────────────────────────────────────


def test_amend_creates_amendment_file_and_bumps_version(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)

    result = _run("amend", "--project", "p", "--task-id", "T",
                  "--summary", "新增 AC 验证项",
                  "--proposer", "user", "--approved-by", "user",
                  "--body", "详细变更说明",
                  base=base)
    assert result.returncode == 0, result.stderr
    spec_dir = base / "p" / "spec" / "T"
    am_files = list((spec_dir / "amendments").glob("*.md"))
    assert len(am_files) == 1
    assert am_files[0].name.startswith("0001-")
    spec_text = (spec_dir / "SPEC.md").read_text(encoding="utf-8")
    assert "version: 0.2" in spec_text
    assert "新增 AC 验证项" in spec_text  # appended history row
    am_text = am_files[0].read_text(encoding="utf-8")
    assert "proposer: user" in am_text
    assert "impact_mode: queue" in am_text


def test_amend_refuses_drafting_spec(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    result = _run("amend", "--project", "p", "--task-id", "T",
                  "--summary", "x", base=base)
    assert result.returncode != 0


def test_amend_impact_mode_recorded(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)
    _run("amend", "--project", "p", "--task-id", "T",
         "--summary", "stop everything", "--impact-mode", "redirect",
         base=base)
    am = next((base / "p" / "spec" / "T" / "amendments").glob("*.md"))
    assert "impact_mode: redirect" in am.read_text(encoding="utf-8")


def test_amend_sequential_numbering(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)
    for i in range(3):
        _run("amend", "--project", "p", "--task-id", "T",
             "--summary", f"change-{i}", base=base)
    names = sorted(f.name for f in (base / "p" / "spec" / "T" / "amendments").glob("*.md"))
    assert names[0].startswith("0001-")
    assert names[1].startswith("0002-")
    assert names[2].startswith("0003-")


# ── verify ────────────────────────────────────────────────────────────────────


def test_verify_runs_assert_commands(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)

    spec_path = base / "p" / "spec" / "T" / "SPEC.md"
    text = spec_path.read_text(encoding="utf-8")
    text = text.replace(
        "| AC-1 | <准则文字> | `assert: <shell-cmd>` | pending |",
        "| AC-1 | passes | `assert: true` | pending |",
    ).replace(
        "| AC-2 | <准则文字> | `script: acceptance/ac2-<slug>.sh` | pending |",
        "| AC-2 | fails | `assert: false` | pending |",
    ).replace(
        "| AC-3 | <准则文字> | 人工 | pending |",
        "| AC-3 | human-pending | 人工 | pending |",
    )
    spec_path.write_text(text, encoding="utf-8")

    result = _run("verify", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode == 2  # AC-2 fails → overall fail
    assert "AC-1 passed" in result.stdout
    assert "AC-2 failed" in result.stdout
    assert "AC-3 manual-pending" in result.stdout


def test_verify_all_pass_returns_zero(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)

    spec_path = base / "p" / "spec" / "T" / "SPEC.md"
    text = spec_path.read_text(encoding="utf-8")
    text = text.replace(
        "| AC-1 | <准则文字> | `assert: <shell-cmd>` | pending |",
        "| AC-1 | true cmd | `assert: true` | pending |",
    ).replace(
        "| AC-2 | <准则文字> | `script: acceptance/ac2-<slug>.sh` | pending |",
        "| AC-2 | echo cmd | `assert: echo ok` | pending |",
    ).replace(
        "| AC-3 | <准则文字> | 人工 | pending |",
        "| AC-3 | already passed | 人工 | passed |",
    )
    spec_path.write_text(text, encoding="utf-8")

    result = _run("verify", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode == 0, result.stdout


def test_verify_rejects_drafting_spec(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    result = _run("verify", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode != 0


# ── close ─────────────────────────────────────────────────────────────────────


def test_close_transitions_status(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    _run("lock", "--project", "p", "--task-id", "T", base=base)
    result = _run("close", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode == 0
    text = (base / "p" / "spec" / "T" / "SPEC.md").read_text(encoding="utf-8")
    assert "status: closed" in text


def test_close_rejects_drafting_spec(tmp_path: Path) -> None:
    base = tmp_path / "specs"
    _run("create", "--project", "p", "--task-id", "T", "--title", "x", base=base)
    result = _run("close", "--project", "p", "--task-id", "T", base=base)
    assert result.returncode != 0
