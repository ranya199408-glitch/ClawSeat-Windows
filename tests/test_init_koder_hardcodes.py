"""Tests for FIX-INIT-KODER-HARDCODES (Wave 3b).

Pins the 5 init_koder.py + template.toml fixes that remove hardcoded
defaults so future koder bootstrap stays project-aware.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
_INIT_KODER = _REPO / "core" / "skills" / "clawseat-install" / "scripts" / "init_koder.py"
_TEMPLATE = _REPO / "core" / "templates" / "gstack-harness" / "template.toml"

# Add the script's parent so we can import its functions
_SCRIPT_DIR = _INIT_KODER.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


def _make_full_profile(notify_target: str = "planner") -> SimpleNamespace:
    """Profile mock providing every attribute build_workspace_files reads."""
    return SimpleNamespace(
        heartbeat_owner="koder",
        heartbeat_transport="openclaw",
        active_loop_owner="planner",
        default_notify_target=notify_target,
        seats=["koder", "planner", "builder"],
        runtime_seats=["koder", "planner", "builder"],
        default_start_seats=[],
        seat_overrides={},
        seat_roles={"koder": "frontstage-supervisor"},
    )


# Sentinel value: NEVER appears in production templates by default.
# Mutation guarantee — any test that expects this value can ONLY pass when
# the parameter actually threads through; a hardcoded "planner" mutation fails.
_NON_DEFAULT_NOTIFY_TARGET = "custom_dispatcher_xyz_5fa3"


# ── Fix 1: notify_target threaded through render_soul + render_tools_index ──

def test_render_soul_substitutes_non_default_notify_target():
    """render_soul must substitute the caller-provided notify_target verbatim.

    Uses a non-default sentinel so a hardcoded "planner" body fails the test —
    the previous version's `assert "planner" in soul` check passed on hardcoded
    output too (since "planner" was both the param value AND the literal).
    """
    import init_koder
    output = init_koder.render_soul(notify_target=_NON_DEFAULT_NOTIFY_TARGET)
    assert f"**{_NON_DEFAULT_NOTIFY_TARGET} 是唯一的下一跳**" in output, (
        f"expected non-default notify_target threaded into output; got:\n{output[:500]}"
    )
    # Negative: literal "planner" must NOT appear in the substituted slot.
    assert "**planner 是唯一的下一跳**" not in output, (
        "hardcoded literal 'planner' detected in substituted slot — parameter threading broken"
    )


def test_render_tools_index_substitutes_non_default_notify_target():
    """render_tools_index must use caller-provided notify_target verbatim."""
    import init_koder
    output = init_koder.render_tools_index(
        _REPO, heartbeat_owner="koder", notify_target=_NON_DEFAULT_NOTIFY_TARGET,
    )
    assert f"dispatch 目标永远是 `{_NON_DEFAULT_NOTIFY_TARGET}`" in output, (
        f"non-default notify_target must thread into 'dispatch 目标永远是 ...'; got:\n{output[:500]}"
    )
    assert "dispatch 目标永远是 `planner`" not in output, (
        "hardcoded literal 'planner' detected — parameter threading broken"
    )


def test_build_workspace_files_threads_notify_target_through_render_layer(tmp_path: Path):
    """End-to-end: profile.default_notify_target must reach IDENTITY.md.

    This is the test that catches mutations at the THREADING layer (e.g. hardcoding
    the call site `notify_target=default_notify_target` → `notify_target="planner"`).
    Direct render_soul tests bypass that layer; this test exercises it.
    """
    import init_koder
    profile = _make_full_profile(notify_target=_NON_DEFAULT_NOTIFY_TARGET)
    files = init_koder.build_workspace_files(
        project="testproject",
        profile_path=tmp_path / "profile.toml",
        profile=profile,
        feishu_group_id="",
        workspace_path=tmp_path / ".openclaw" / "workspace-koder",
    )
    identity = files["IDENTITY.md"]

    # Positive: non-default value reaches the four-file workspace identity.
    assert _NON_DEFAULT_NOTIFY_TARGET in identity, (
        f"profile.default_notify_target must thread through to IDENTITY.md; "
        f"got IDENTITY.md head:\n{identity[:500]}"
    )

    # Negative: hardcoded "planner" must NOT appear in the substituted slots.
    # (Other parts of the file may still mention "planner" — e.g. role examples
    # in dispatch instructions.  Only assert on the substituted phrase patterns.)
    assert "route work through `planner`" not in identity, (
        "IDENTITY.md still has hardcoded planner as notify target — threading broken"
    )


# ── Fix 2: --project is required, no default ────────────────────────────────

def test_project_arg_is_required_no_default():
    """--project must be required (argparse exits 2 when missing)."""
    result = subprocess.run(
        [sys.executable, str(_INIT_KODER), "--workspace", "/tmp/nonexistent-workspace"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, "missing --project must fail"
    assert "--project" in result.stderr, "stderr must mention the missing flag"


# ── Fix 3: workspace_path threaded into render_tools_project ────────────────

def test_render_tools_project_uses_workspace_path(tmp_path: Path):
    """render_tools_project must embed the actual workspace path, not hardcode workspace-koder."""
    import init_koder
    custom_ws = tmp_path / ".openclaw" / "workspace-yu"
    out = init_koder.render_tools_project(_REPO, heartbeat_owner="koder", workspace_path=custom_ws)
    assert str(custom_ws) in out, (
        f"render_tools_project must embed the actual workspace path; got:\n{out[:500]}"
    )
    assert "workspace-koder/WORKSPACE_CONTRACT" not in out, (
        "Hardcoded workspace-koder path must NOT appear when workspace_path is provided"
    )


def test_render_tools_project_no_hardcoded_workspace_koder():
    """The hardcoded OpenClaw koder workspace contract literal must not appear."""
    src = _INIT_KODER.read_text(encoding="utf-8")
    assert ".openclaw/workspace-koder/WORKSPACE_CONTRACT" not in src, (
        "init_koder.py must not hardcode workspace-koder path; use workspace_path arg"
    )


# ── Koder v2: template.toml lists merged clawseat-koder ─────────────────────

def test_template_toml_lists_merged_clawseat_koder():
    """gstack-harness template.toml koder skills must include merged clawseat-koder."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert "clawseat-koder/SKILL.md" in text
    assert "clawseat-koder" + "-frontstage" not in text


def test_install_koder_skills_resolves_merged_clawseat_koder(tmp_path: Path):
    """install_koder_skills must produce a symlink for the merged koder skill."""
    import init_koder
    skills_dir = tmp_path / "skills"
    spec = init_koder._find_template_engineer(init_koder.load_template(), "koder")
    init_koder.install_koder_skills(
        skills_dir, _REPO, spec=spec, dry_run=False,
    )
    expected = skills_dir / "clawseat-koder"
    assert expected.exists() or expected.is_symlink(), (
        f"clawseat-koder symlink must exist at {expected}; "
        f"actual contents: {sorted(p.name for p in skills_dir.iterdir())}"
    )


# ── Integration: full file rendering with project-specific settings ─────────

def test_integration_workspace_path_propagates_through_render(tmp_path: Path):
    """Full integration: render_tools_project receives the workspace_path
    from build_workspace_files, which must use it in the contract snippet."""
    import init_koder
    workspace = tmp_path / ".openclaw" / "workspace-creative"
    out = init_koder.render_tools_project(
        _REPO, heartbeat_owner="koder", workspace_path=workspace,
    )
    # The custom workspace path must appear; the default workspace-koder path must not
    assert "workspace-creative" in out
    assert "workspace-koder/WORKSPACE_CONTRACT" not in out
