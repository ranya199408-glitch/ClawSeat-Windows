"""Harness profile dataclasses and loading."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from _utils import AGENTS_ROOT, REPO_ROOT, load_toml, sanitize_name

from ._utils import _unique_seats, expand_profile_value, infer_role_from_seat_id, role_sort_key
from .session import discovered_session_data

__all__ = [
    "ObservabilityConfig",
    "HarnessProfile",
    "resolve_dynamic_seats",
    "load_profile",
    "render_project_doc",
    "render_tasks_doc",
    "render_status_doc",
]


@dataclass
class ObservabilityConfig:
    announce_planner_events: bool = False


@dataclass
class HarnessProfile:
    # Canonical project/runtime contract used by the legacy harness path.
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
    # Legacy frontstage transport shims. Layered v2 profiles move these
    # semantics to PROJECT_BINDING + machine/tenant config; keep them here
    # only because the legacy harness scripts still need to route koder/openclaw.
    heartbeat_owner: str
    heartbeat_transport: str
    active_loop_owner: str
    default_notify_target: str
    heartbeat_receipt: Path
    seats: list[str]
    heartbeat_seats: list[str]
    seat_roles: dict[str, str]
    seat_overrides: dict[str, dict[str, str]]
    # Legacy/local-override compatibility fields. These are not canonical v2
    # profile schema fields; they survive here so pre-v2 harness/runtime files
    # can still describe which seats were materialized into tmux.
    dynamic_roster_enabled: bool = False
    runtime_seats: list[str] | None = None
    session_root: Path = Path()
    materialized_seats: list[str] | None = None
    bootstrap_seats: list[str] | None = None
    default_start_seats: list[str] | None = None
    compat_legacy_seats: bool = False
    legacy_seats: list[str] | None = None
    legacy_seat_roles: dict[str, str] | None = None
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

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

    def declared_project_seats(self) -> list[str]:
        return list(self.seats)

    def tmux_runtime_seats(self) -> list[str]:
        if self.runtime_seats is not None:
            return list(self.runtime_seats)
        if self.materialized_seats is not None:
            return list(self.materialized_seats)
        return self.declared_project_seats()

    def compat_materialized_seats(self) -> list[str]:
        return list(self.materialized_seats or self.seats)

    def frontstage_target_seat(self) -> str:
        return str(self.heartbeat_owner).strip()

    def frontstage_transport_kind(self) -> str:
        return str(self.heartbeat_transport).strip().lower() or "tmux"

    def declared_runtime_seats(self) -> list[str]:
        return self.tmux_runtime_seats()

    def seat_runs_in_tmux(self, seat: str) -> bool:
        if seat == self.frontstage_target_seat() and self.frontstage_transport_kind() == "openclaw":
            return False
        return seat in set(self.tmux_runtime_seats())

    def heartbeat_runs_in_openclaw(self) -> bool:
        return self.frontstage_transport_kind() == "openclaw"

def resolve_dynamic_seats(
    *,
    heartbeat_owner: str,
    declared_seats: list[str],
    compat_materialized_seats: list[str],
    compat_legacy_seats: bool,
    legacy_seats: list[str],
    discovered_sessions: dict[str, dict[str, Any]],
    seat_roles: dict[str, str],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    groups = [
        [heartbeat_owner],
        declared_seats,
        compat_materialized_seats,
        legacy_seats if compat_legacy_seats else [],
        sorted(
            discovered_sessions.keys(),
            key=lambda seat: role_sort_key(
                seat,
                seat_roles.get(seat, ""),
                heartbeat_owner=heartbeat_owner,
            ),
        ),
    ]
    for group in groups:
        for seat in group:
            if not seat or seat in seen:
                continue
            seen.add(seat)
            ordered.append(seat)
    return ordered


def load_profile(path: str | Path) -> HarnessProfile:
    try:
        import tomllib as _tomllib
    except ModuleNotFoundError:
        import tomli as _tomllib  # type: ignore

    profile_path = Path(path).expanduser().resolve()
    data = _tomllib.loads(profile_path.read_text(encoding="utf-8"))
    dynamic = data.get("dynamic_roster", {})
    if not isinstance(dynamic, dict):
        dynamic = {}
    dynamic_enabled = bool(dynamic.get("enabled", False))
    session_root = expand_profile_value(str(dynamic.get("session_root", AGENTS_ROOT / "sessions")))
    # Legacy harness loader: keep reading the old frontstage/runtime transport
    # hints here because local override TOMLs and pre-v2 profiles still carry
    # them. Layered v2 profiles intentionally removed these keys from the
    # canonical schema.
    compat_frontstage_owner = str(data.get("heartbeat_owner", "koder"))
    compat_frontstage_transport = (
        str(data.get("heartbeat_transport", "tmux")).strip().lower() or "tmux"
    )
    if compat_frontstage_transport not in {"tmux", "openclaw"}:
        raise ValueError(
            f"invalid heartbeat_transport {compat_frontstage_transport!r} in {profile_path}; "
            "expected 'tmux' or 'openclaw'"
        )
    legacy_seat_roles = {
        str(key): str(value)
        for key, value in data.get("legacy_seat_roles", {}).items()
    }
    legacy_seats = [str(item) for item in data.get("legacy_seats", list(legacy_seat_roles.keys()))]
    declared_seats = [str(item) for item in data.get("seats", [])]
    compat_materialized_seats = [
        str(item)
        for item in dynamic.get("materialized_seats", declared_seats)
    ]
    compat_bootstrap_seats = [
        str(item)
        for item in dynamic.get("bootstrap_seats", [compat_frontstage_owner])
    ]
    compat_default_start_seats = [
        str(item)
        for item in dynamic.get(
            "default_start_seats",
            compat_bootstrap_seats or compat_materialized_seats,
        )
    ]
    compat_runtime_seats_raw = dynamic.get("runtime_seats")
    if compat_runtime_seats_raw is None:
        compat_runtime_seats = list(compat_materialized_seats or declared_seats)
        if compat_frontstage_transport == "openclaw":
            compat_runtime_seats = [
                seat for seat in compat_runtime_seats if seat != compat_frontstage_owner
            ]
    else:
        compat_runtime_seats = [str(item) for item in compat_runtime_seats_raw]
    compat_legacy_seats = bool(dynamic.get("compat_legacy_seats", False))
    discovered = discovered_session_data(session_root, str(data["project_name"])) if dynamic_enabled else {}
    seat_roles = {str(k): str(v) for k, v in data.get("seat_roles", {}).items()}
    seat_roles.update(legacy_seat_roles)
    for seat, session in discovered.items():
        role = str(session.get("role", "")).strip()
        seat_roles[seat] = infer_role_from_seat_id(
            seat,
            fallback=role or seat_roles.get(seat, ""),
            heartbeat_owner=compat_frontstage_owner,
        )
    seats = (
        resolve_dynamic_seats(
            heartbeat_owner=compat_frontstage_owner,
            declared_seats=declared_seats,
            compat_materialized_seats=compat_materialized_seats,
            compat_legacy_seats=compat_legacy_seats,
            legacy_seats=legacy_seats,
            discovered_sessions=discovered,
            seat_roles=seat_roles,
        )
        if dynamic_enabled
        else [str(item) for item in data.get("seats", [])]
    )
    compat_runtime_seats = _unique_seats(compat_runtime_seats)
    return HarnessProfile(
        profile_path=profile_path,
        profile_name=str(data["profile_name"]),
        template_name=str(data["template_name"]),
        project_name=str(data["project_name"]),
        repo_root=expand_profile_value(str(data["repo_root"])),
        tasks_root=expand_profile_value(str(data["tasks_root"])),
        project_doc=expand_profile_value(str(data["project_doc"])),
        tasks_doc=expand_profile_value(str(data["tasks_doc"])),
        status_doc=expand_profile_value(str(data["status_doc"])),
        send_script=expand_profile_value(str(data["send_script"])),
        # v0.4 migration stripped these fields (see schema §7). Provide
        # sane defaults so v2 profiles load cleanly:
        #   active_loop_owner → "memory" (the v2 L3 hub)
        #   default_notify_target → "memory"
        #   status_script / patrol_script / heartbeat_receipt → empty
        status_script=expand_profile_value(str(data.get("status_script", ""))),
        patrol_script=expand_profile_value(str(data.get("patrol_script", ""))),
        agent_admin=expand_profile_value(str(data["agent_admin"])),
        workspace_root=expand_profile_value(str(data["workspace_root"])),
        handoff_dir=expand_profile_value(str(data["handoff_dir"])),
        heartbeat_owner=compat_frontstage_owner,
        heartbeat_transport=compat_frontstage_transport,
        active_loop_owner=str(data.get("active_loop_owner", "memory")),
        default_notify_target=str(data.get("default_notify_target", "memory")),
        heartbeat_receipt=expand_profile_value(str(data.get("heartbeat_receipt", ""))),
        seats=seats,
        runtime_seats=compat_runtime_seats,
        heartbeat_seats=[str(item) for item in data.get("heartbeat_seats", [])],
        seat_roles=seat_roles,
        seat_overrides={
            str(seat_id): {str(k): str(v) for k, v in values.items()}
            for seat_id, values in data.get("seat_overrides", {}).items()
        },
        dynamic_roster_enabled=dynamic_enabled,
        session_root=session_root,
        materialized_seats=compat_materialized_seats,
        bootstrap_seats=compat_bootstrap_seats,
        default_start_seats=compat_default_start_seats,
        compat_legacy_seats=compat_legacy_seats,
        legacy_seats=legacy_seats,
        legacy_seat_roles=legacy_seat_roles,
        observability=ObservabilityConfig(
            announce_planner_events=bool(
                data.get("observability", {}).get("announce_planner_events", False)
            )
        ),
    )
def render_project_doc(profile: HarnessProfile) -> str:
    role_lines = []
    for seat in profile.seats:
        role = profile.seat_roles.get(seat, "specialist")
        role_lines.append(f"- `{seat}` = `{role}`")
    chain_owner = profile.active_loop_owner if profile.active_loop_owner in profile.seats else "planner"
    return (
        f"# {profile.project_name} Harness Project\n\n"
        "This project is managed by `gstack-harness`.\n\n"
        "## Seats\n\n"
        + "\n".join(role_lines)
        + "\n\n## Chain\n\n"
        + (
            f"`user -> {profile.heartbeat_owner} -> {chain_owner} -> specialist -> "
            f"{chain_owner} -> ... -> {profile.heartbeat_owner} -> user`\n"
            if chain_owner != profile.heartbeat_owner
            else f"`user -> {profile.heartbeat_owner} -> specialist -> {profile.heartbeat_owner} -> user`\n"
        )
    )

def render_tasks_doc() -> str:
    return "# Tasks\n\n| ID | Title | Owner | Status | Notes |\n|----|-------|-------|--------|-------|\n"

def render_status_doc() -> str:
    return "# Status\n"
