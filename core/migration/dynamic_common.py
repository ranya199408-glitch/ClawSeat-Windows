#!/usr/bin/env python3
# DEPRECATED (2026-04-22): shared support code for transitional
# dynamic-roster compatibility shims. Remove only after the router cleanup no
# longer needs to bridge legacy/static callers.
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


# Resolve ORIGINAL_COMMON relative to this file — no hardcoded maintainer path needed.
_MIGRATION_DIR = Path(__file__).resolve().parent  # .../ClawSeat/core/migration
_CLAWSEAT_ROOT_FOR_COMMON = _MIGRATION_DIR.parent.parent  # .../ClawSeat
if str(_CLAWSEAT_ROOT_FOR_COMMON) not in sys.path:
    sys.path.insert(0, str(_CLAWSEAT_ROOT_FOR_COMMON))
_HARNESS_SCRIPTS_DIR = _CLAWSEAT_ROOT_FOR_COMMON / "core" / "skills" / "gstack-harness" / "scripts"
ORIGINAL_COMMON = _HARNESS_SCRIPTS_DIR / "_common.py"

# `_common.py` internally does bare-name `from _utils import ...` etc.;
# those sibling modules only resolve if the harness scripts dir is on
# sys.path *before* we exec the module. Without this prepend, invoking
# any migration entry point (dispatch_task_dynamic, notify_seat_dynamic,
# ...) as a top-level script dies at import time with `ModuleNotFoundError:
# No module named '_utils'`. Smoke test `test_migration_script_help_runs`
# locks this in.
if str(_HARNESS_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_SCRIPTS_DIR))

from core.lib.real_home import real_user_home

SPEC = importlib.util.spec_from_file_location("gstack_harness_common_dynamic", ORIGINAL_COMMON)
if SPEC is None or SPEC.loader is None:
    raise SystemExit(f"unable to load harness common module from {ORIGINAL_COMMON}")
BASE_COMMON = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE_COMMON
SPEC.loader.exec_module(BASE_COMMON)

ROLE_PREFIX_RE = re.compile(r"^(?P<role>[a-z0-9-]+)-(?P<index>\d+)$")
ROLE_PRIORITY = {
    "frontstage-supervisor": 0,
    "planner-dispatcher": 1,
    "planner": 1,
    "builder": 2,
    "reviewer": 3,
    "patrol": 4,
    "qa": 4,
    "designer": 5,
    "specialist": 50,
}


@dataclass
class HarnessProfile:
    profile_path: Path
    profile_name: str
    template_name: str
    project_name: str
    repo_root: Path
    tasks_root: Path
    project_doc: Path
    tasks_doc: Path
    status_doc: Path
    send_script: Path
    status_script: Path
    patrol_script: Path
    agent_admin: Path
    workspace_root: Path
    handoff_dir: Path
    heartbeat_owner: str
    heartbeat_transport: str
    active_loop_owner: str
    default_notify_target: str
    heartbeat_receipt: Path
    seats: list[str]
    heartbeat_seats: list[str]
    seat_roles: dict[str, str]
    seat_overrides: dict[str, dict[str, str]]
    dynamic_roster_enabled: bool
    runtime_seats: list[str]
    session_root: Path
    materialized_seats: list[str]
    bootstrap_seats: list[str]
    default_start_seats: list[str]
    compat_legacy_seats: bool
    legacy_seats: list[str]
    legacy_seat_roles: dict[str, str]
    patrol_enabled: bool
    planner_brief_path: Path

    def todo_path(self, seat: str) -> Path:
        return self.tasks_root / seat / "TODO.md"

    def delivery_path(self, seat: str) -> Path:
        return self.tasks_root / seat / "DELIVERY.md"

    def handoff_path(self, task_id: str, source: str, target: str) -> Path:
        safe_task = sanitize_name(task_id)
        safe_source = sanitize_name(source)
        safe_target = sanitize_name(target)
        return self.handoff_dir / f"{safe_task}__{safe_source}__{safe_target}.json"

    def workspace_for(self, seat: str) -> Path:
        return self.workspace_root / seat

    def heartbeat_receipt_for(self, seat: str) -> Path:
        return self.workspace_for(seat) / "HEARTBEAT_RECEIPT.toml"

    def seat_runs_in_tmux(self, seat: str) -> bool:
        # Mirrors HarnessProfile.seat_runs_in_tmux in
        # core/skills/gstack-harness/scripts/_common.py: an openclaw
        # frontstage owner is not a tmux seat even if it appears in the
        # profile's seats list.
        if seat == self.heartbeat_owner and self.heartbeat_transport == "openclaw":
            return False
        return seat in set(self.runtime_seats)


assert_target_not_memory = BASE_COMMON.assert_target_not_memory
add_notify_args = BASE_COMMON.add_notify_args
resolve_notify = BASE_COMMON.resolve_notify
MEMORY_SEAT_NAME = BASE_COMMON.MEMORY_SEAT_NAME
MEMORY_QUERY_POINTER = BASE_COMMON.MEMORY_QUERY_POINTER
sanitize_name = BASE_COMMON.sanitize_name
utc_now_iso = BASE_COMMON.utc_now_iso
ensure_dir = BASE_COMMON.ensure_dir
ensure_parent = BASE_COMMON.ensure_parent
read_text = BASE_COMMON.read_text
write_text = BASE_COMMON.write_text
load_json = BASE_COMMON.load_json
load_toml = BASE_COMMON.load_toml
write_json = BASE_COMMON.write_json
run_command = BASE_COMMON.run_command
run_command_with_env = BASE_COMMON.run_command_with_env
require_success = BASE_COMMON.require_success
notify = BASE_COMMON.notify
resolve_session_name = BASE_COMMON.resolve_session_name
build_notify_message = BASE_COMMON.build_notify_message
build_notify_payload = BASE_COMMON.build_notify_payload
build_completion_message = BASE_COMMON.build_completion_message
upsert_tasks_row = BASE_COMMON.upsert_tasks_row
append_status_note = BASE_COMMON.append_status_note
write_todo = BASE_COMMON.write_todo
write_delivery = BASE_COMMON.write_delivery
append_consumed_ack = BASE_COMMON.append_consumed_ack
find_consumed_ack = BASE_COMMON.find_consumed_ack
extract_canonical_verdict = BASE_COMMON.extract_canonical_verdict
extract_prefixed_value = BASE_COMMON.extract_prefixed_value
file_declares_task = BASE_COMMON.file_declares_task
handoff_assigned = BASE_COMMON.handoff_assigned
heartbeat_manifest_fingerprint = BASE_COMMON.heartbeat_manifest_fingerprint
heartbeat_receipt_is_verified = BASE_COMMON.heartbeat_receipt_is_verified
heartbeat_state = BASE_COMMON.heartbeat_state
make_local_override = BASE_COMMON.make_local_override
summarize_status_lines = BASE_COMMON.summarize_status_lines
executable_command = BASE_COMMON.executable_command
heartbeat_manifest_path = BASE_COMMON.heartbeat_manifest_path
heartbeat_md_path = BASE_COMMON.heartbeat_md_path
session_path_for = BASE_COMMON.session_path_for
session_name_for = BASE_COMMON.session_name_for
capture_session_pane = BASE_COMMON.capture_session_pane
detect_claude_onboarding_step = BASE_COMMON.detect_claude_onboarding_step
render_tasks_doc = BASE_COMMON.render_tasks_doc
render_status_doc = BASE_COMMON.render_status_doc
render_patrol_wrapper = BASE_COMMON.render_patrol_wrapper
is_managed_runtime_path = BASE_COMMON.is_managed_runtime_path
seed_empty_secret_from_peer = BASE_COMMON.seed_empty_secret_from_peer
# seed_empty_oauth_runtime_from_peer was removed — OAuth tokens are
# user-managed via the TUI, not seeded by the harness.
send_feishu_user_message = BASE_COMMON.send_feishu_user_message
broadcast_feishu_group_message = BASE_COMMON.broadcast_feishu_group_message
stable_dispatch_nonce = BASE_COMMON.stable_dispatch_nonce


def load_raw_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def normalize_role(role: str) -> str:
    if role in {"planner", "planner-dispatcher"}:
        return "planner"
    if role.startswith("designer"):
        return "designer"
    return role or "specialist"


def seat_sort_key(seat: str, role: str, *, heartbeat_owner: str = "") -> tuple[int, str]:
    if (heartbeat_owner and seat == heartbeat_owner) or normalize_role(role) == "frontstage-supervisor":
        return (0, seat)
    normalized = normalize_role(role)
    return (ROLE_PRIORITY.get(role, ROLE_PRIORITY.get(normalized, 50)), seat)


def unique_ordered(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for group in groups:
        for item in group:
            if item in seen or not item:
                continue
            seen.add(item)
            ordered.append(item)
    return ordered


def discovered_session_data(session_root: Path, project_name: str) -> dict[str, dict[str, Any]]:
    project_root = session_root / project_name
    if not project_root.exists():
        return {}
    discovered: dict[str, dict[str, Any]] = {}
    for session_path in sorted(project_root.glob("*/session.toml")):
        session = load_toml(session_path) or {}
        seat = str(session.get("engineer_id", session_path.parent.name)).strip() or session_path.parent.name
        discovered[seat] = session
    return discovered


def infer_role_from_seat_id(seat: str, fallback: str = "", *, heartbeat_owner: str = "") -> str:
    if fallback:
        return fallback
    if heartbeat_owner and seat == heartbeat_owner:
        return "frontstage-supervisor"
    if seat == "planner":
        return "planner"
    match = ROLE_PREFIX_RE.match(seat)
    if match:
        return match.group("role")
    return "specialist"


def resolve_roles(
    *,
    top_level_roles: dict[str, str],
    legacy_roles: dict[str, str],
    discovered_sessions: dict[str, dict[str, Any]],
    heartbeat_owner: str,
) -> dict[str, str]:
    resolved = dict(top_level_roles)
    resolved.update(legacy_roles)
    for seat, session in discovered_sessions.items():
        role = str(session.get("role", "")).strip()
        resolved[seat] = infer_role_from_seat_id(
            seat,
            fallback=role or resolved.get(seat, ""),
            heartbeat_owner=heartbeat_owner,
        )
    return resolved


def resolve_dynamic_seats(
    *,
    heartbeat_owner: str,
    declared_seats: list[str],
    materialized_seats: list[str],
    compat_legacy_seats: bool,
    legacy_seats: list[str],
    discovered_sessions: dict[str, dict[str, Any]],
    seat_roles: dict[str, str],
) -> list[str]:
    discovered = sorted(
        discovered_sessions.keys(),
        key=lambda seat: seat_sort_key(
            seat,
            seat_roles.get(seat, ""),
            heartbeat_owner=heartbeat_owner,
        ),
    )
    seats = unique_ordered(
        [heartbeat_owner],
        declared_seats,
        materialized_seats,
        legacy_seats if compat_legacy_seats else [],
        discovered,
    )
    return seats


def load_profile(path: str | Path) -> HarnessProfile:
    profile_path = Path(path).expanduser()
    data = load_raw_toml(profile_path)
    dynamic = data.get("dynamic_roster", {})
    patrol = data.get("patrol", {})
    if not isinstance(dynamic, dict):
        dynamic = {}
    if not isinstance(patrol, dict):
        patrol = {}
    legacy_roles = {
        str(key): str(value)
        for key, value in data.get("legacy_seat_roles", {}).items()
    }
    legacy_seats = [str(item) for item in data.get("legacy_seats", list(legacy_roles.keys()))]
    top_level_roles = {str(k): str(v) for k, v in data.get("seat_roles", {}).items()}
    session_root = Path(str(dynamic.get("session_root", str(real_user_home() / ".agents" / "sessions")))).expanduser()
    heartbeat_owner = str(data["heartbeat_owner"])
    heartbeat_transport = str(data.get("heartbeat_transport", "tmux")).strip().lower() or "tmux"
    declared_seats = [str(item) for item in data.get("seats", [heartbeat_owner])]
    materialized_seats = [str(item) for item in dynamic.get("materialized_seats", declared_seats)]
    runtime_seats_raw = dynamic.get("runtime_seats")
    if runtime_seats_raw is None:
        runtime_seats = list(materialized_seats)
        if heartbeat_transport == "openclaw":
            runtime_seats = [seat for seat in runtime_seats if seat != heartbeat_owner]
    else:
        runtime_seats = [str(item) for item in runtime_seats_raw]
    bootstrap_seats = [str(item) for item in dynamic.get("bootstrap_seats", [heartbeat_owner])]
    default_start_seats = [str(item) for item in dynamic.get("default_start_seats", bootstrap_seats or materialized_seats)]
    dynamic_enabled = bool(dynamic.get("enabled", False))
    compat_legacy_seats = bool(dynamic.get("compat_legacy_seats", False))
    discovered = discovered_session_data(session_root, str(data["project_name"])) if dynamic_enabled else {}
    seat_roles = resolve_roles(
        top_level_roles=top_level_roles,
        legacy_roles=legacy_roles,
        discovered_sessions=discovered,
        heartbeat_owner=heartbeat_owner,
    )
    seats = (
        resolve_dynamic_seats(
            heartbeat_owner=heartbeat_owner,
            declared_seats=declared_seats,
            materialized_seats=materialized_seats,
            compat_legacy_seats=compat_legacy_seats,
            legacy_seats=legacy_seats,
            discovered_sessions=discovered,
            seat_roles=seat_roles,
        )
        if dynamic_enabled
        else [str(item) for item in data.get("seats", [])]
    )
    active_loop_owner = str(data["active_loop_owner"])
    if dynamic_enabled and active_loop_owner not in seats:
        if "planner" in seats:
            active_loop_owner = "planner"
        elif heartbeat_owner in seats:
            active_loop_owner = heartbeat_owner
    default_notify_target = str(data["default_notify_target"])
    if dynamic_enabled and default_notify_target not in seats:
        default_notify_target = active_loop_owner
    heartbeat_seats = [str(item) for item in data.get("heartbeat_seats", default_start_seats or [heartbeat_owner])]
    planner_brief_path = Path(
        str(patrol.get("planner_brief_path", str(Path(str(data["tasks_root"])).expanduser() / "planner" / "PLANNER_BRIEF.md")))
    ).expanduser()
    return HarnessProfile(
        profile_path=profile_path,
        profile_name=str(data["profile_name"]),
        template_name=str(data["template_name"]),
        project_name=str(data["project_name"]),
        repo_root=Path(str(data["repo_root"])).expanduser(),
        tasks_root=Path(str(data["tasks_root"])).expanduser(),
        project_doc=Path(str(data["project_doc"])).expanduser(),
        tasks_doc=Path(str(data["tasks_doc"])).expanduser(),
        status_doc=Path(str(data["status_doc"])).expanduser(),
        send_script=Path(str(data["send_script"])).expanduser(),
        status_script=Path(str(data["status_script"])).expanduser(),
        patrol_script=Path(str(data["patrol_script"])).expanduser(),
        agent_admin=Path(str(data["agent_admin"])).expanduser(),
        workspace_root=Path(str(data["workspace_root"])).expanduser(),
        handoff_dir=Path(str(data["handoff_dir"])).expanduser(),
        heartbeat_owner=heartbeat_owner,
        heartbeat_transport=heartbeat_transport,
        active_loop_owner=active_loop_owner,
        default_notify_target=default_notify_target,
        heartbeat_receipt=Path(str(data["heartbeat_receipt"])).expanduser(),
        seats=seats,
        heartbeat_seats=heartbeat_seats,
        seat_roles=seat_roles,
        seat_overrides={
            str(seat_id): {str(k): str(v) for k, v in values.items()}
            for seat_id, values in data.get("seat_overrides", {}).items()
        },
        dynamic_roster_enabled=dynamic_enabled,
        runtime_seats=runtime_seats,
        session_root=session_root,
        materialized_seats=materialized_seats,
        bootstrap_seats=bootstrap_seats,
        default_start_seats=default_start_seats,
        compat_legacy_seats=compat_legacy_seats,
        legacy_seats=legacy_seats,
        legacy_seat_roles=legacy_roles,
        patrol_enabled=bool(patrol.get("enabled", False)),
        planner_brief_path=planner_brief_path,
    )


def tracked_runtime_seats(profile: HarnessProfile) -> list[str]:
    bound = []
    for seat in profile.runtime_seats:
        session_path = profile.session_root / profile.project_name / seat / "session.toml"
        if session_path.exists():
            bound.append(seat)
    if bound:
        return bound
    return list(profile.runtime_seats)


def preferred_planner_seat(profile: HarnessProfile) -> str:
    planner_candidates = [
        seat
        for seat in profile.seats
        if normalize_role(profile.seat_roles.get(seat, "")) == "planner"
    ]
    if "planner" in planner_candidates:
        return "planner"
    if profile.active_loop_owner in planner_candidates:
        return profile.active_loop_owner
    if planner_candidates:
        return sorted(planner_candidates)[0]
    if profile.active_loop_owner in profile.seats:
        return profile.active_loop_owner
    if profile.default_notify_target in profile.seats:
        return profile.default_notify_target
    return profile.heartbeat_owner


def render_project_doc(profile: HarnessProfile) -> str:
    role_lines = []
    for seat in profile.seats:
        role = profile.seat_roles.get(seat, "specialist")
        role_lines.append(f"- `{seat}` = `{role}`")
    chain_owner = profile.active_loop_owner if profile.active_loop_owner in profile.seats else "planner"
    if chain_owner == profile.heartbeat_owner:
        chain = f"`user -> {profile.heartbeat_owner} -> specialist -> {profile.heartbeat_owner} -> user`"
    else:
        chain = (
            f"`user -> {profile.heartbeat_owner} -> {chain_owner} -> specialist -> "
            f"{chain_owner} -> ... -> {profile.heartbeat_owner} -> user`"
        )
    return (
        f"# {profile.project_name} Harness Project\n\n"
        "This project is managed by `gstack-harness` with dynamic roster discovery.\n\n"
        "## Seats\n\n"
        + "\n".join(role_lines)
        + "\n\n## Chain\n\n"
        + chain
        + "\n"
    )


def render_status_wrapper(profile: HarnessProfile) -> str:
    seats = " ".join(tracked_runtime_seats(profile))
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n\n"
        f"export TASKS_ROOT={profile.tasks_root}\n"
        f"export PATROL_DIR={profile.tasks_root / 'patrol'}\n"
        f"export DEFAULT_SESSIONS=\"{seats}\"\n\n"
        "exec \"${CLAWSEAT_ROOT:-$(cd \"$(dirname \"$(readlink -f \"$0\")\")/../../..\" && pwd)}/core/shell-scripts/check-engineer-status.sh\" \"$@\"\n"
    )


def render_heartbeat_md(profile: HarnessProfile, seat: str) -> str:
    role = profile.seat_roles.get(seat, "frontstage-supervisor")
    next_hop = profile.active_loop_owner if profile.active_loop_owner in profile.seats else profile.heartbeat_owner
    return (
        f"# {seat} heartbeat\n\n"
        f"Runtime seat id: `{seat}`\n"
        f"Canonical role: `{role}`\n\n"
        "Dynamic roster: seat list is derived from the profile's `seats` + discovered sessions.\n"
        "All role-to-seat routing is driven by the active profile.\n"
        f"- active loop owner: `{profile.active_loop_owner}`\n"
        f"- next hop for chain: `{next_hop}`\n"
    )


def render_heartbeat_manifest(profile: HarnessProfile, seat: str) -> str:
    commands = [
        str(profile.patrol_script),
        f"{profile.patrol_script} --send",
    ]
    workspace = profile.workspace_for(seat)
    receipt = profile.heartbeat_receipt_for(seat)
    lines = [
        "version = 1",
        f'seat_id = "{seat}"',
        f'project = "{profile.project_name}"',
        f'role = "{profile.seat_roles.get(seat, "frontstage-supervisor")}"',
        'kind = "heartbeat"',
        "enabled = true",
        "interval_minutes = 15",
        f'active_loop_owner = "{profile.active_loop_owner}"',
        'expected_idle_reply = "HEARTBEAT_OK"',
        f'workspace = "{workspace}"',
        f'repo_root = "{profile.repo_root}"',
        f'receipt_path = "{receipt}"',
        f'patrol_entrypoint = "{profile.status_script}"',
        f'supervisor_entrypoint = "{profile.patrol_script}"',
        f'send_script = "{profile.send_script}"',
        f'commands = {json.dumps(commands, ensure_ascii=False)}',
        "",
    ]
    return "\n".join(lines)


def materialize_profile_runtime(profile: HarnessProfile) -> None:
    ensure_dir(profile.tasks_root)
    ensure_dir(profile.handoff_dir)
    for seat in profile.seats:
        ensure_dir(profile.tasks_root / seat)
    if not profile.project_doc.exists():
        write_text(profile.project_doc, render_project_doc(profile))
    if not profile.tasks_doc.exists():
        write_text(profile.tasks_doc, render_tasks_doc())
    if not profile.status_doc.exists():
        write_text(profile.status_doc, BASE_COMMON.render_status_doc())
    if is_managed_runtime_path(profile, profile.status_script):
        write_text(profile.status_script, render_status_wrapper(profile))
        profile.status_script.chmod(0o755)
    if is_managed_runtime_path(profile, profile.patrol_script):
        write_text(profile.patrol_script, BASE_COMMON.render_patrol_wrapper(profile))
        profile.patrol_script.chmod(0o755)
    for seat in profile.heartbeat_seats:
        # Skip heartbeat manifest/md for seats that don't run in tmux — the
        # generated docs describe a tmux-only patrol transport that cannot
        # reach an openclaw frontstage.
        if not profile.seat_runs_in_tmux(seat):
            continue
        ensure_dir(profile.workspace_for(seat))
        write_text(heartbeat_md_path(profile, seat), render_heartbeat_md(profile, seat))
        write_text(heartbeat_manifest_path(profile, seat), render_heartbeat_manifest(profile, seat))
