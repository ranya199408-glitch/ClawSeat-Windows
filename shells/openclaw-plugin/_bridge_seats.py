"""
Seat operations for OpenClaw <-> ClawSeat bridge.

Covers team status, task dispatch, seat instantiation, planner state reading,
project switching, seat status check, and team summary.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.adapter.clawseat_adapter import (
    AdapterResult,
    BriefState,
    ClawseatAdapter,
    PendingFrontstageItem,
    SessionStatus,
)
from core.lib.real_home import real_user_home

from _bridge_adapters import init_clawseat_adapter, init_tmux_adapter


# ---------------------------------------------------------------------------
# Team status operations
# ---------------------------------------------------------------------------


def list_team_sessions(
    project_name: str,
    *,
    tmux_adapter: Any | None = None,
) -> list[dict[str, Any]]:
    """
    List all tmux sessions for the given project via TmuxCliAdapter.

    Returns a list of session handles with seat_id, tool, runtime_id, etc.
    """
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()

    handles = tmux_adapter.list_sessions(project_name)
    return [
        {
            "seat_id": h.seat_id,
            "project": h.project,
            "tool": h.tool,
            "runtime_id": h.runtime_id,
            "workspace_path": h.workspace_path,
            "session_path": h.session_path,
            "locator": h.locator,
        }
        for h in handles
    ]


def probe_seat_state(
    handle: dict[str, Any],
    *,
    tmux_adapter: Any | None = None,
) -> str:
    """
    Probe the state of a seat session.

    Returns one of: auth_needed, onboarding, running, ready, degraded, dead
    """
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()

    from core.harness_adapter import SessionHandle

    session_handle = SessionHandle(
        seat_id=handle["seat_id"],
        project=handle["project"],
        tool=handle["tool"],
        runtime_id=handle["runtime_id"],
        workspace_path=handle.get("workspace_path", ""),
        session_path=handle.get("session_path", ""),
    )
    return tmux_adapter.probe_state(session_handle).value


def probe_seat_state_detailed(
    handle: dict[str, Any],
    *,
    tmux_adapter: Any | None = None,
) -> dict[str, Any]:
    """
    Probe the state of a seat session with degraded sub-reason classification.

    Returns dict with:
      - state: one of auth_needed, onboarding, running, ready, degraded, dead
      - degraded_reason: 'authz' (403/forbidden), 'quota' (429/rate limit), or None
    """
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()

    from core.harness_adapter import SessionHandle

    session_handle = SessionHandle(
        seat_id=handle["seat_id"],
        project=handle["project"],
        tool=handle["tool"],
        runtime_id=handle["runtime_id"],
        workspace_path=handle.get("workspace_path", ""),
        session_path=handle.get("session_path", ""),
    )
    state, reason, observable = tmux_adapter.probe_state_detailed(session_handle)
    return {
        "state": state.value,
        "degraded_reason": reason,
        "current_task_id": observable.current_task_id,
        "needs_input": observable.needs_input,
        "input_reason": observable.input_reason,
        "last_prompt_excerpt": observable.last_prompt_excerpt,
    }


def resume_seat_if_needed(
    handle: dict[str, Any],
    *,
    tmux_adapter: Any | None = None,
) -> dict[str, Any]:
    """
    Attempt to resume a seat session, with differentiated strategy based on state.

    - 429/quota DEGRADED: auto-send "continue" (resume)
    - 403/authz DEGRADED: do NOT auto-recover, return BLOCKED_ESCALATION
    - Other states: use standard resume logic
    """
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()

    from core.harness_adapter import SessionHandle

    session_handle = SessionHandle(
        seat_id=handle["seat_id"],
        project=handle["project"],
        tool=handle["tool"],
        runtime_id=handle["runtime_id"],
        workspace_path=handle.get("workspace_path", ""),
        session_path=handle.get("session_path", ""),
    )

    state, reason, _observable = tmux_adapter.probe_state_detailed(session_handle)

    if state.value == "degraded":
        if reason == "authz":
            return {
                "action": "BLOCKED_ESCALATION",
                "reason": "authz",
                "state": state.value,
                "delivered": False,
                "detail": "403/forbidden detected \u2014 must escalate to user",
            }
        elif reason == "quota":
            result = tmux_adapter.send_message(session_handle, "\u7ee7\u7eed")
            return {
                "action": "auto_resume",
                "reason": "quota",
                "state": state.value,
                "delivered": result.delivered,
                "detail": result.detail,
            }
        else:
            result = tmux_adapter.send_message(session_handle, "\u7ee7\u7eed")
            return {
                "action": "auto_resume",
                "reason": "generic",
                "state": state.value,
                "delivered": result.delivered,
                "detail": result.detail,
            }

    result = tmux_adapter.resume_session(session_handle)
    return {
        "action": "resume",
        "state": result.state.value,
        "resumed": result.resumed,
        "detail": result.detail,
    }


# ---------------------------------------------------------------------------
# Task dispatch
# ---------------------------------------------------------------------------


def dispatch_task_to_planner(
    *,
    project_name: str,
    task_id: str,
    title: str,
    objective: str,
    test_policy: str = "UPDATE",
    source: str = "koder",
    target: str | None = None,
    reply_to: str | None = None,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> AdapterResult:
    """
    Dispatch a task to the planner via ClawSeatAdapter.

    Dynamically resolves the planner target if not explicitly provided.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    resolved_target = target
    if resolved_target is None:
        try:
            planner_info = clawseat_adapter.resolve_planner(project_name=project_name)
            resolved_target = planner_info["planner_instance"]
        except Exception as primary_err:
            # Fallback: try active_loop_owner from the same profile snapshot
            try:
                planner_info = clawseat_adapter.resolve_planner(project_name=project_name)
                resolved_target = planner_info.get("active_loop_owner", "")
            except Exception:
                pass
            if not resolved_target:
                raise RuntimeError(
                    f"dispatch_task_to_planner: cannot resolve planner target for project "
                    f"{project_name!r} (tried planner_instance and active_loop_owner): {primary_err}"
                )

    return clawseat_adapter.dispatch_task(
        project_name=project_name,
        source=source,
        target=resolved_target,
        task_id=task_id,
        title=title,
        objective=objective,
        test_policy=test_policy,
        reply_to=reply_to,
    )


# ---------------------------------------------------------------------------
# Seat instantiation
# ---------------------------------------------------------------------------


def instantiate_seat(
    *,
    project_name: str,
    template_id: str,
    instance_id: str | None = None,
    repo_root: str | Path | None = None,
    force: bool = False,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> dict[str, Any]:
    """
    Instantiate a new seat via ClawSeatAdapter + TmuxCliAdapter.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    result = clawseat_adapter.instantiate_seat(
        project_name=project_name,
        template_id=template_id,
        instance_id=instance_id,
        repo_root=repo_root,
        force=force,
    )
    return result


def start_seat_via_tmux(
    seat_id: str,
    project_name: str,
    *,
    tmux_adapter: Any | None = None,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> dict[str, Any]:
    """
    Start a seat session via TmuxCliAdapter.
    """
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    from core.harness_adapter import SeatPlan

    session_path = Path(os.environ.get("SESSIONS_ROOT", str(real_user_home() / ".agents" / "sessions"))) / project_name / seat_id / "session.toml"
    if not session_path.exists():
        raise FileNotFoundError(f"session binding not found: {session_path}")

    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib

    with session_path.open("rb") as f:
        binding = tomllib.load(f)

    seat_plan = SeatPlan(
        seat_id=seat_id,
        project=project_name,
        role=binding.get("role", ""),
        tool=binding.get("tool", ""),
        workspace_path=binding.get("workspace", ""),
        contract_content={},
        session_binding_spec=binding,
    )

    handle = tmux_adapter.start_session(seat_id, project_name, seat_plan)
    return {
        "seat_id": handle.seat_id,
        "project": handle.project,
        "tool": handle.tool,
        "runtime_id": handle.runtime_id,
        "workspace_path": handle.workspace_path,
        "session_path": handle.session_path,
    }


# ---------------------------------------------------------------------------
# Planner state reading
# ---------------------------------------------------------------------------


def read_planner_brief(
    project_name: str,
    *,
    profile_path: str | Path | None = None,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> BriefState:
    """
    Read the current PLANNER_BRIEF for the project.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    return clawseat_adapter.read_brief(project_name=project_name, profile_path=profile_path)


def read_pending_frontstage(
    project_name: str,
    *,
    profile_path: str | Path | None = None,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> list[PendingFrontstageItem]:
    """
    Read unresolved PENDING_FRONTSTAGE items for the project.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    return clawseat_adapter.read_pending_frontstage(project_name=project_name, profile_path=profile_path)


# ---------------------------------------------------------------------------
# Project switching
# ---------------------------------------------------------------------------


def switch_project(
    project_name: str,
    *,
    profile_path: str | Path | None = None,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> dict[str, Any]:
    """
    Switch the ClawSeatAdapter's active project.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    return clawseat_adapter.switch_project(project_name=project_name, profile_path=profile_path)


# ---------------------------------------------------------------------------
# Seat status check
# ---------------------------------------------------------------------------


def check_seat_status(
    project_name: str,
    seat_id: str,
    *,
    clawseat_adapter: ClawseatAdapter | None = None,
) -> SessionStatus:
    """
    Check the status of a specific seat via ClawSeatAdapter.
    """
    if clawseat_adapter is None:
        clawseat_adapter = init_clawseat_adapter(project_name=project_name)

    return clawseat_adapter.check_session(project_name=project_name, seat_id=seat_id)


# ---------------------------------------------------------------------------
# Team summary
# ---------------------------------------------------------------------------


def get_team_summary(
    project_name: str,
    *,
    tmux_adapter: Any | None = None,
) -> list[dict[str, Any]]:
    """
    Return a structured summary of all seat states for the given project.

    Each entry contains: seat_id, state, degraded_reason, current_task_id,
    needs_input, input_reason, last_prompt_excerpt.
    """
    if tmux_adapter is None:
        tmux_adapter = init_tmux_adapter()

    sessions = list_team_sessions(project_name, tmux_adapter=tmux_adapter)
    summary: list[dict[str, Any]] = []

    from core.harness_adapter import SessionHandle

    for session in sessions:
        handle = SessionHandle(
            seat_id=session["seat_id"],
            project=session["project"],
            tool=session["tool"],
            runtime_id=session["runtime_id"],
            workspace_path=session.get("workspace_path", ""),
            session_path=session.get("session_path", ""),
        )
        state, reason, observable = tmux_adapter.probe_state_detailed(handle)
        summary.append({
            "seat_id": session["seat_id"],
            "state": state.value,
            "degraded_reason": reason,
            "current_task_id": observable.current_task_id,
            "needs_input": observable.needs_input,
            "input_reason": observable.input_reason,
            "last_prompt_excerpt": observable.last_prompt_excerpt,
        })

    return summary
