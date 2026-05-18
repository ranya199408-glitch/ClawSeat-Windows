#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_CORE_LIB = _SCRIPT_DIR.parents[2] / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))
from utils import load_toml, q, q_array


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert a fixed harness profile into a dynamic-roster profile.")
    parser.add_argument("--source-profile", required=True, help="Existing profile.toml path.")
    parser.add_argument("--output-profile", required=True, help="Destination dynamic profile path.")
    parser.add_argument("--project-name", help="Optional project-name override.")
    parser.add_argument("--repo-root", help="Optional repo-root override.")
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Generate a new-project profile that only bootstraps koder and does not preserve legacy seats.",
    )
    return parser.parse_args()


def resolve_clawseat_root() -> Path:
    configured = os.environ.get("CLAWSEAT_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[4]


def build_lines(data: dict[str, Any], *, project_name: str, repo_root: str, bootstrap_only: bool) -> list[str]:
    tasks_root = f"~/.agents/tasks/{project_name}"
    workspace_root = f"~/.agents/workspaces/{project_name}"
    heartbeat_owner = str(data.get("heartbeat_owner", "koder"))
    active_loop_owner = str(data.get("active_loop_owner", "memory"))
    default_notify_target = str(data.get("default_notify_target", "memory"))
    legacy_seat_roles = {str(k): str(v) for k, v in data.get("seat_roles", {}).items() if str(k) != heartbeat_owner}
    legacy_seats = [seat for seat in data.get("seats", []) if str(seat) != heartbeat_owner]
    if bootstrap_only:
        active_loop_owner = "memory"
        default_notify_target = "memory"
        legacy_seat_roles = {}
        legacy_seats = []

    # Koder is an OpenClaw agent, not a ClawSeat tmux/materialized seat. Keep
    # backend seats in the profile roster and put koder receipts under
    # ~/.openclaw so the generated profile does not create a fake koder
    # workspace under ~/.agents/workspaces/<project>/.
    heartbeat_transport = "tmux"
    materialized_seats_list = [str(seat) for seat in legacy_seats]
    runtime_seats_list = list(materialized_seats_list)
    heartbeat_receipt = f"~/.openclaw/koder/{project_name}-HEARTBEAT_RECEIPT.toml"

    lines = [
        "version = 2",
        f'profile_name = {q(str(data.get("profile_name", project_name + ".dynamic")))}',
        f'description = {q(str(data.get("description", "dynamic-roster harness profile")))}',
        f'template_name = {q("gstack-harness-dynamic-roster")}',
        f'project_name = {q(project_name)}',
        f'repo_root = {q(repo_root)}',
        f'tasks_root = {q(tasks_root)}',
        f'project_doc = {q(tasks_root + "/PROJECT.md")}',
        f'tasks_doc = {q(tasks_root + "/TASKS.md")}',
        f'status_doc = {q(tasks_root + "/STATUS.md")}',
        f'send_script = {q(str(data["send_script"]))}',
        f'status_script = {q(tasks_root + "/patrol/check-status.sh")}',
        f'patrol_script = {q(tasks_root + "/patrol/patrol-supervisor.sh")}',
        f'agent_admin = {q(str(data["agent_admin"]))}',
        f'workspace_root = {q(workspace_root)}',
        f'handoff_dir = {q(tasks_root + "/patrol/handoffs")}',
        f'heartbeat_owner = {q(heartbeat_owner)}',
        f'heartbeat_transport = {q(heartbeat_transport)}',
        f'active_loop_owner = {q(active_loop_owner)}',
        f'default_notify_target = {q(default_notify_target)}',
        f'heartbeat_receipt = {q(heartbeat_receipt)}',
        f'seats = {q_array(materialized_seats_list)}',
        f'heartbeat_seats = {q_array([])}',
        "",
        "[seat_roles]",
        'koder = "frontstage-supervisor"',
        "",
        "[dynamic_roster]",
        "enabled = true",
        'session_root = "~/.agents/sessions"',
        f'materialized_seats = {q_array(materialized_seats_list)}',
        f'runtime_seats = {q_array(runtime_seats_list)}',
        f'bootstrap_seats = {q_array([])}',
        f'default_start_seats = {q_array(materialized_seats_list)}',
        f"compat_legacy_seats = {'false' if bootstrap_only else 'true'}",
        "",
        f"legacy_seats = {q_array([str(seat) for seat in legacy_seats])}",
        "",
        "[legacy_seat_roles]",
    ]
    if legacy_seat_roles:
        for seat, role in legacy_seat_roles.items():
            lines.append(f"{seat} = {q(role)}")
    lines.extend(
        [
            "",
            "[patrol]",
            "enabled = false",
            f'planner_brief_path = {q(tasks_root + "/planner/PLANNER_BRIEF.md")}',
        ]
    )
    return lines


def main() -> int:
    args = parse_args()
    source_profile = Path(args.source_profile).expanduser()
    output_profile = Path(args.output_profile).expanduser()
    data = load_toml(source_profile)
    project_name = args.project_name or str(data["project_name"])
    repo_root = args.repo_root or str(resolve_clawseat_root())
    lines = build_lines(
        data,
        project_name=project_name,
        repo_root=repo_root,
        bootstrap_only=args.bootstrap_only,
    )
    output_profile.parent.mkdir(parents=True, exist_ok=True)
    output_profile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
