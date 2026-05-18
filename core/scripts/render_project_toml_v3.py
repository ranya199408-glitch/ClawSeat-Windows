#!/usr/bin/env python3
"""Render v3 project.toml from approved config proposals.

Phase 1 minimal multi-mode render path. Called by install.sh --mode multi.

Pipeline:
1. Read tasks/<project>/_config-proposals/*__approved.yaml
2. Validate via proposal_validator
3. Emit v3 project.toml to --output path

The resulting project.toml:
- Stays loader-compatible (top-level `seats`, `[seat_roles]`, flat `[seat_overrides.*]`)
- Adds `[mode]` + `[teams]` metadata for v3 loader (profile_loader_v3.py)

See spec §4.1, §9.2, §16.7 (install-spec-2026-05-13-clawseat-v3-multi-team-protocol.md).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

try:
    import yaml  # type: ignore
except ImportError:
    print("PyYAML required", file=sys.stderr)
    raise SystemExit(1)

from proposal_validator import (  # noqa: E402
    ProposalValidationError,
    assert_all_valid,
    validate_proposal_dir,
)


def _load_yaml_proposal(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end == -1:
            end = text.find("\n---", 4)
        if end != -1:
            text = text[4:end]
    return yaml.safe_load(text)


def _toml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _toml_array(items: list[str]) -> str:
    quoted = [_toml_quote(s) for s in items]
    return "[\n  " + ",\n  ".join(quoted) + ",\n]"


def render_project_toml_v3(
    project: str,
    proposals_dir: Path,
    repo_root: str | None = None,
    teams_filter: list[str] | None = None,
) -> str:
    """Generate the project.toml text from approved config proposals.

    If teams_filter is given, only those teams are rendered. Unknown team
    names (not present in proposals_dir as <team>__approved.yaml) hard-fail.
    None / empty list ⇒ render all approved teams.

    Caller is expected to have run `assert_all_valid(proposals_dir)` first;
    we re-run it here defensively because rendering a broken toml is worse
    than failing loudly.
    """
    assert_all_valid(proposals_dir)

    all_files = sorted(Path(proposals_dir).glob("*__approved.yaml"))
    if not all_files:
        raise RuntimeError(f"no approved configs in {proposals_dir}")

    available_teams = {f.name.removesuffix("__approved.yaml"): f for f in all_files}

    if teams_filter:
        requested = [t.strip() for t in teams_filter if t.strip()]
        unknown = [t for t in requested if t not in available_teams]
        if unknown:
            raise RuntimeError(
                f"unknown team(s) requested via --teams: {unknown}; "
                f"approved teams available: {sorted(available_teams)}"
            )
        team_files = [available_teams[t] for t in requested]
    else:
        team_files = all_files

    teams: dict[str, list[str]] = {}
    all_seats: list[str] = []
    seat_roles: dict[str, str] = {}
    seat_overrides: dict[str, dict[str, object]] = {}

    for f in team_files:
        data = _load_yaml_proposal(f)
        team_name = str(data.get("team") or "").strip()
        if not team_name:
            raise RuntimeError(f"{f.name}: missing 'team' field")

        # post-review fix #3: cross-field validation
        yaml_project = str(data.get("project") or "").strip()
        if yaml_project and yaml_project != project:
            raise RuntimeError(
                f"{f.name}: project mismatch — yaml says {yaml_project!r}, "
                f"CLI --project says {project!r}; refusing to render"
            )
        filename_team = f.name.removesuffix("__approved.yaml")
        if team_name != filename_team:
            raise RuntimeError(
                f"{f.name}: team field {team_name!r} does not match filename "
                f"team prefix {filename_team!r}; refusing to render"
            )
        team_seat_ids: list[str] = []
        for seat in data.get("seats") or []:
            role = str(seat["role"]).strip()
            seat_id = f"{team_name}-{role}"
            team_seat_ids.append(seat_id)
            all_seats.append(seat_id)
            seat_roles[seat_id] = role
            override: dict[str, object] = {
                "tool": str(seat["tool"]),
                "provider": str(seat["provider"]),
                "auth_mode": str(seat["auth_mode"]),
            }
            # Preserve concrete model id from approved config (post-review fix #1).
            # Approved yaml may omit model only for tools where provider implies it.
            if seat.get("model"):
                override["model"] = str(seat["model"])
            if seat.get("purpose"):
                override["purpose"] = str(seat["purpose"])
            caps = seat.get("capabilities")
            if caps:
                override["capabilities"] = list(caps)
            seat_overrides[seat_id] = override
        teams[team_name] = team_seat_ids

    # Sanity: no duplicate seat ids across teams
    if len(set(all_seats)) != len(all_seats):
        dupes = [s for s in all_seats if all_seats.count(s) > 1]
        raise RuntimeError(f"duplicate seat ids across teams: {sorted(set(dupes))}")

    # Determine paths needed by the runtime harness profile loader (post-retest #1).
    # See core/skills/gstack-harness/scripts/_common/profile.py:240+ for required keys.
    home_env = os.environ.get("CLAWSEAT_REAL_HOME") or os.environ.get("HOME") or str(Path.home())
    clawseat_root = os.environ.get("CLAWSEAT_ROOT") or str(Path(__file__).resolve().parents[2])
    agents_root = f"{home_env}/.agents"
    tasks_root = f"{agents_root}/tasks/{project}"
    workspace_root = f"{agents_root}/workspaces/{project}"
    handoff_dir = f"{tasks_root}/patrol/handoffs"

    lines: list[str] = []
    lines.append(f"# Generated by render_project_toml_v3.py for project {project!r}")
    lines.append(f"# Rendered from {proposals_dir}")
    lines.append("")
    # All top-level scalar/array keys MUST come before any [table] section.
    lines.append(f"profile_name = {_toml_quote(f'{project}-profile-dynamic')}")
    lines.append(f"template_name = {_toml_quote('clawseat-engineering')}")
    lines.append(f"project_name = {_toml_quote(project)}")
    if repo_root:
        lines.append(f"repo_root = {_toml_quote(repo_root)}")
    else:
        lines.append(f"repo_root = {_toml_quote(clawseat_root)}")
    lines.append(f"tasks_root = {_toml_quote(tasks_root)}")
    lines.append(f"project_doc = {_toml_quote(f'{tasks_root}/project.md')}")
    lines.append(f"tasks_doc = {_toml_quote(f'{tasks_root}/TASKS.md')}")
    lines.append(f"status_doc = {_toml_quote(f'{tasks_root}/STATUS.md')}")
    lines.append(f"send_script = {_toml_quote(f'{clawseat_root}/core/shell-scripts/send-and-verify.sh')}")
    lines.append(f"agent_admin = {_toml_quote(f'{clawseat_root}/core/scripts/agent_admin.py')}")
    lines.append(f"workspace_root = {_toml_quote(workspace_root)}")
    lines.append(f"handoff_dir = {_toml_quote(handoff_dir)}")
    lines.append("")
    lines.append("# Loader-compatible flat seats (read by existing profile.py)")
    lines.append(f"seats = {_toml_array(all_seats)}")
    lines.append("")
    lines.append("# v3 mode + teams metadata (read by core/lib/profile_loader_v3.py)")
    lines.append("[mode]")
    lines.append('team_structure = "multi"')
    lines.append("")
    lines.append("[teams]")
    for team_name in teams:
        # Inline table with seats array
        seat_list = ", ".join(_toml_quote(s) for s in teams[team_name])
        lines.append(f"{team_name} = {{ seats = [{seat_list}] }}")
    lines.append("")
    lines.append("[seat_roles]")
    for seat_id, role in seat_roles.items():
        lines.append(f"{seat_id} = {_toml_quote(role)}")
    lines.append("")
    for seat_id, override in seat_overrides.items():
        lines.append(f"[seat_overrides.{seat_id}]")
        for key, val in override.items():
            if isinstance(val, list):
                lines.append(f"{key} = {_toml_array([str(x) for x in val])}")
            else:
                lines.append(f"{key} = {_toml_quote(str(val))}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render v3 project.toml from approved config proposals."
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--proposals-dir", required=True,
                        help="Path to tasks/<project>/_config-proposals/")
    parser.add_argument("--output", default="-",
                        help="Output path (default '-' for stdout)")
    parser.add_argument("--repo-root", default=None,
                        help="Optional repo_root absolute path to embed in project.toml")
    parser.add_argument("--teams", default=None,
                        help="Comma-separated team filter (default: all approved). "
                             "Unknown teams hard-fail.")
    args = parser.parse_args(argv)

    teams_filter = None
    if args.teams:
        teams_filter = [t.strip() for t in args.teams.split(",") if t.strip()]

    try:
        toml_text = render_project_toml_v3(
            project=args.project,
            proposals_dir=Path(args.proposals_dir),
            repo_root=args.repo_root,
            teams_filter=teams_filter,
        )
    except ProposalValidationError as exc:
        for v in exc.violations:
            print(f"  ✗ {v}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"render failed: {exc}", file=sys.stderr)
        return 1

    if args.output == "-":
        sys.stdout.write(toml_text)
    else:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(toml_text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
