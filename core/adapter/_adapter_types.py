"""Dataclasses and type definitions for the ClawSeat adapter layer."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AdapterResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class BriefAction:
    requested_operation: str
    target_role: str
    target_instance: str
    template_id: str
    reason: str
    resume_task: str


@dataclass
class BriefState:
    project_name: str
    profile_path: str
    brief_path: str
    title: str
    owner: str
    status: str
    updated: str
    frontstage_disposition: str
    user_summary: str
    action: BriefAction


@dataclass
class SessionStatus:
    project_name: str
    seat_id: str
    session_path: str
    session_name: str
    exists: bool
    tmux_running: bool
    runtime_dir: str
    workspace: str
    tool: str
    provider: str
    auth_mode: str


@dataclass
class PendingFrontstageItem:
    item_id: str
    item_type: str
    related_task: str
    summary: str
    planner_recommendation: str
    koder_default_action: str
    user_input_needed: bool
    blocking: bool
    options: list[str]
    resolved: bool
    resolved_by: str
    resolved_at: str
    resolution: str
    section: str


@dataclass
class PendingProjectOperation:
    kind: str
    project_name: str
    frontstage_epoch: int
    profile_path: str
    payload: dict[str, Any]


__all__ = [
    "AdapterResult",
    "BriefAction",
    "BriefState",
    "PendingFrontstageItem",
    "PendingProjectOperation",
    "SessionStatus",
]
