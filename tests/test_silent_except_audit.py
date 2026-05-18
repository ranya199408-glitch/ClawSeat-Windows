"""Guard tests for T3 bundle-B: silent except audit.

Ensures:
- No broad 'except Exception: pass' in /core
- No bare 'except: pass' in /core
- Every silent except...:pass in the 8 audited files has a '# silent-ok:' sentinel
- _common.py's agent_admin_config load block warns to stderr on ImportError
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_CORE = _REPO / "core"

# The 8 files audited in T3 bundle-B
_AUDITED = [
    _CORE / "skills" / "gstack-harness" / "scripts" / "_common.py",
    _CORE / "preflight.py",
    _CORE / "skills" / "memory-oracle" / "scripts" / "_memory_paths.py",
    _CORE / "skills" / "memory-oracle" / "scripts" / "scan_environment.py",
    _CORE / "skills" / "memory-oracle" / "scripts" / "memory_deliver.py",
    _CORE / "skills" / "gstack-harness" / "scripts" / "start_seat.py",
    _CORE / "skills" / "gstack-harness" / "scripts" / "_feishu.py",
]


def _py_files():
    return [
        p for p in _CORE.rglob("*.py")
        if "__pycache__" not in p.parts
    ]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def test_no_broad_except_in_core():
    """No 'except Exception:' followed by a bare pass in core."""
    broad_pat = re.compile(r"except\s+Exception\s*:\s*\n\s+pass\b")
    violations = []
    for p in _py_files():
        text = _read(p)
        if broad_pat.search(text):
            violations.append(str(p.relative_to(_REPO)))
    assert violations == [], f"Broad except Exception:pass found in: {violations}"


def test_no_bare_except_in_core():
    """No bare 'except:' followed by a bare pass in core."""
    bare_pat = re.compile(r"except\s*:\s*\n\s+pass\b")
    violations = []
    for p in _py_files():
        text = _read(p)
        if bare_pat.search(text):
            violations.append(str(p.relative_to(_REPO)))
    assert violations == [], f"Bare except:pass found in: {violations}"


def test_all_silent_excepts_have_sentinel():
    """Every 'except ...: pass' in the 8 audited files has a '# silent-ok:' sentinel."""
    silent_pat = re.compile(
        r"^(?P<indent>[ \t]*)except[^\n]*:\s*\n"
        r"(?P=indent)[ \t]+pass\s*$",
        re.MULTILINE,
    )
    violations = []
    for p in _AUDITED:
        if not p.exists():
            continue
        text = _read(p)
        lines = text.splitlines()
        for m in silent_pat.finditer(text):
            line_no = text[: m.start()].count("\n")
            window_start = max(0, line_no - 1)
            window_end = min(len(lines), line_no + 3)
            window = "\n".join(lines[window_start:window_end])
            if "# silent-ok:" not in window:
                violations.append(
                    f"{p.relative_to(_REPO)}:{line_no + 1} — missing # silent-ok:"
                )
    assert violations == [], "Silent excepts without sentinel:\n" + "\n".join(violations)


def test_common_agent_admin_config_load_warns(tmp_path):
    """_patch_claude_settings_from_profile warns to stderr when agent_admin_config raises ImportError.

    Creates a fake CLAWSEAT_ROOT with a poison agent_admin_config.py that raises
    ImportError on exec. The real gstack-harness template is used for template.toml.
    Uses sys.executable to ensure the same interpreter with all dependencies.
    """
    scripts_dir = str(_CORE / "skills" / "gstack-harness" / "scripts")
    real_repo = str(_REPO)

    # Set up a fake repo root with a poison agent_admin_config.py
    fake_root = tmp_path / "fakerepo"
    # Copy the real template so the function doesn't early-return
    import shutil
    real_templates = _REPO / "core" / "templates"
    fake_templates = fake_root / "core" / "templates"
    shutil.copytree(real_templates, fake_templates)
    # Create a poison agent_admin_config.py that raises ImportError when exec'd
    fake_scripts = fake_root / "core" / "scripts"
    fake_scripts.mkdir(parents=True)
    (fake_scripts / "agent_admin_config.py").write_text(
        "raise ImportError('poison: intentionally broken for test')\n",
        encoding="utf-8",
    )

    script = f"""\
import sys, pathlib
sys.path.insert(0, {scripts_dir!r})
import _common

p = pathlib.Path
hp = _common.HarnessProfile(
    profile_path=p("/tmp/fake.toml"),
    profile_name="fake",
    template_name="gstack-harness",
    project_name="fake",
    repo_root=p({str(fake_root)!r}),
    tasks_root=p("/tmp/tasks"),
    project_doc=p("/tmp/proj.md"),
    tasks_doc=p("/tmp/tasks.md"),
    status_doc=p("/tmp/status.md"),
    send_script=p("/tmp/send.sh"),
    status_script=p("/tmp/status.sh"),
    patrol_script=p("/tmp/patrol.sh"),
    agent_admin=p("/tmp/agent_admin.py"),
    workspace_root=p("/tmp/workspaces"),
    handoff_dir=p("/tmp/handoffs"),
    heartbeat_owner="koder",
    heartbeat_transport="tmux",
    active_loop_owner="planner",
    default_notify_target="planner",
    heartbeat_receipt=p("/tmp/receipt.toml"),
    seats=[],
    heartbeat_seats=[],
    seat_roles={{}},
    seat_overrides={{}},
)
_common._patch_claude_settings_from_profile(hp, [])
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "CLAWSEAT_ROOT": str(fake_root)},
    )
    assert "warn: agent_admin_config load failed" in result.stderr, (
        f"Expected warning in stderr, got: {result.stderr!r}\n"
        f"stdout: {result.stdout!r}\n"
        f"returncode: {result.returncode}"
    )


def test_sentinel_format_enforced():
    """Every '# silent-ok:' comment must have >3 characters of rationale after the colon."""
    sentinel_pat = re.compile(r"#\s*silent-ok:\s*(?P<reason>.*)$", re.MULTILINE)
    violations = []
    for p in _py_files():
        text = _read(p)
        for m in sentinel_pat.finditer(text):
            reason = m.group("reason").strip()
            if len(reason) <= 3:
                line_no = text[: m.start()].count("\n") + 1
                violations.append(
                    f"{p.relative_to(_REPO)}:{line_no} — reason too short: {reason!r}"
                )
    assert violations == [], "Thin silent-ok rationale:\n" + "\n".join(violations)
