#!/usr/bin/env python3
"""
refresh_workspaces.py — Regenerate all seat workspace files after ClawSeat update.

Auto-detects project, profile, koder workspace, and feishu group ID.
Designed to be called by the OpenClaw koder agent with zero arguments:

    python3 refresh_workspaces.py

Or with explicit overrides:

    python3 refresh_workspaces.py --project myapp --koder-workspace /path/to/ws
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
_core = str(REPO_ROOT / "core")
if _core not in sys.path:
    sys.path.insert(0, _core)

_harness_scripts = str(REPO_ROOT / "core" / "skills" / "gstack-harness" / "scripts")
if _harness_scripts not in sys.path:
    sys.path.insert(0, _harness_scripts)

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

from lib.real_home import real_user_home


# ── Auto-detection helpers ───────────────��───────────────────────────

def _detect_koder_workspace() -> str | None:
    """Find the koder workspace by scanning common locations."""
    candidates = [
        real_user_home() / ".openclaw" / "workspace-koder",
        Path(os.environ.get("OPENCLAW_HOME", "")) / "workspace-koder" if os.environ.get("OPENCLAW_HOME") else None,
    ]
    # Also check if we're running inside a workspace that has WORKSPACE_CONTRACT.toml
    cwd = Path.cwd()
    if (cwd / "WORKSPACE_CONTRACT.toml").exists():
        return str(cwd)
    for c in candidates:
        if c and c.exists() and (c / "WORKSPACE_CONTRACT.toml").exists():
            return str(c)
        if c and c.exists() and (c / "AGENTS.md").exists():
            return str(c)
    return None


def _detect_project_from_contract(koder_ws: str | None) -> str | None:
    """Read project name from koder's WORKSPACE_CONTRACT.toml."""
    if not koder_ws:
        return None
    contract = Path(koder_ws) / "WORKSPACE_CONTRACT.toml"
    if not contract.exists():
        return None
    data = tomllib.loads(contract.read_text(encoding="utf-8"))
    return str(data.get("project", "")).strip() or None


def _detect_feishu_group_id(koder_ws: str | None) -> str:
    """Read feishu_group_id from koder's WORKSPACE_CONTRACT.toml."""
    if not koder_ws:
        return ""
    contract = Path(koder_ws) / "WORKSPACE_CONTRACT.toml"
    if not contract.exists():
        return ""
    data = tomllib.loads(contract.read_text(encoding="utf-8"))
    return str(data.get("feishu_group_id", "")).strip()


def _detect_profile(project: str) -> str | None:
    """Find profile TOML for the project."""
    from resolve import dynamic_profile_path
    p = dynamic_profile_path(project)
    if p.exists():
        return str(p)
    # Legacy fallback
    legacy = Path("/tmp") / f"{project}-profile-dynamic.toml"
    if legacy.exists():
        return str(legacy)
    return None


# ── Refresh logic ─────────────────��──────────────────────────────────

def refresh_backend_seats(profile_path: str, project: str, *, dry_run: bool) -> int:
    from _common import load_profile, materialize_profile_runtime

    profile = load_profile(profile_path)
    agent_admin = REPO_ROOT / "core" / "scripts" / "agent_admin.py"

    print(f"re-applying template '{profile.template_name}' for project '{project}'...")
    result = subprocess.run(
        [
            sys.executable, str(agent_admin),
            "project", "bootstrap",
            "--template", profile.template_name,
            "--local", str(profile.profile_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"warning: agent_admin bootstrap returned {result.returncode}", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)

    if not dry_run:
        print("re-materializing profile runtime...")
        materialize_profile_runtime(profile)

    for seat in profile.seats:
        workspace = profile.workspace_for(seat)
        agents_md = workspace / "AGENTS.md"
        if agents_md.exists():
            print(f"  refreshed: {seat}")

    return 0


def refresh_koder(
    koder_workspace: str,
    project: str,
    profile_path: str,
    feishu_group_id: str,
    *,
    dry_run: bool,
) -> int:
    init_koder = SCRIPT_DIR / "init_koder.py"
    cmd = [
        sys.executable, str(init_koder),
        "--workspace", koder_workspace,
        "--project", project,
        "--profile", profile_path,
        "--feishu-group-id", feishu_group_id,
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"refreshing koder workspace at {koder_workspace}...")
    result = subprocess.run(cmd, text=True, check=False)
    return result.returncode


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Refresh all ClawSeat workspace files. Auto-detects all parameters.",
    )
    p.add_argument("--project", help="Project name. Auto-detected from koder contract if omitted.")
    p.add_argument("--profile", help="Profile TOML path. Auto-detected if omitted.")
    p.add_argument("--koder-workspace", help="Koder workspace path. Auto-detected if omitted.")
    p.add_argument("--feishu-group-id", help="Feishu group ID. Auto-detected from contract if omitted.")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    # Auto-detect everything
    koder_ws = args.koder_workspace or _detect_koder_workspace()
    project = args.project or _detect_project_from_contract(koder_ws) or "install"
    feishu_gid = args.feishu_group_id or _detect_feishu_group_id(koder_ws)
    profile_path = args.profile or _detect_profile(project)

    if not profile_path:
        print(f"error: cannot find profile for project '{project}'", file=sys.stderr)
        print(f"  tried: ~/.agents/profiles/{project}-profile-dynamic.toml", file=sys.stderr)
        return 1

    print(f"project:         {project}")
    print(f"profile:         {profile_path}")
    print(f"koder workspace: {koder_ws or '(not found, skipping koder refresh)'}")
    print(f"feishu group:    {feishu_gid or '(not set)'}")
    print()

    errors = 0

    # 1. Refresh backend seats
    rc = refresh_backend_seats(profile_path, project, dry_run=args.dry_run)
    if rc != 0:
        errors += 1

    # 2. Refresh koder
    if koder_ws:
        rc = refresh_koder(koder_ws, project, profile_path, feishu_gid, dry_run=args.dry_run)
        if rc != 0:
            errors += 1
    else:
        print("skipping koder refresh (workspace not found)")

    if errors == 0:
        print(f"\nall workspaces refreshed for project '{project}'")
        print("koder should re-read AGENTS.md and TOOLS.md now.")
    else:
        print(f"\nrefresh completed with {errors} error(s)", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
