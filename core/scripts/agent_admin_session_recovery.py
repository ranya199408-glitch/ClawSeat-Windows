from __future__ import annotations

from agent_admin_session_base import (
    sys,
    time,
    Any,
    TMUX_COMMAND_RETRIES,
    TMUX_COMMAND_RETRY_DELAY_SECONDS,
    SessionStartError,
)


class SessionRecovery:
    def project_engineer_context(self, project: Any) -> tuple[dict[str, Any], list[str]]:
        context = self.hooks.project_template_context(project)
        if context:
            template_profiles, engineer_order, _ = context
            return template_profiles, engineer_order
        engineers = self.hooks.load_engineers()
        return engineers, list(project.engineers)

    def project_autostart_engineer_ids(self, project: Any, *, ensure_monitor: bool = False) -> list[str]:
        engineer_map, engineer_order = self.project_engineer_context(project)
        ordered_ids = [engineer_id for engineer_id in engineer_order if engineer_id in project.engineers]
        if not ordered_ids:
            ordered_ids = list(project.engineers)

        if ensure_monitor and project.window_mode != "tabs-1up":
            # Skip frontstage engineers (koder/frontstage) — they are
            # OpenClaw-managed agents, not tmux seats. Auto-spawning them
            # creates a ghost tmux session that displaces the real OpenClaw
            # identity. See agent_admin_window._is_frontstage_engineer.
            visible_ids = [
                engineer_id
                for engineer_id in project.monitor_engineers[: max(1, project.monitor_max_panes)]
                if engineer_id in project.engineers
                and engineer_id not in {"koder", "frontstage"}
            ]
            if visible_ids:
                return visible_ids

        frontstage_ids = [
            engineer_id
            for engineer_id in ordered_ids
            if engineer_map.get(engineer_id)
            and engineer_map[engineer_id].patrol_authority
            and engineer_map[engineer_id].remind_active_loop_owner
        ]
        if frontstage_ids:
            return frontstage_ids

        human_facing_ids = [
            engineer_id
            for engineer_id in ordered_ids
            if engineer_map.get(engineer_id) and engineer_map[engineer_id].human_facing
        ]
        if human_facing_ids:
            return human_facing_ids[:1]

        return ordered_ids[:1]

    def start_project(self, project: Any, ensure_monitor: bool = True, reset: bool = False) -> None:
        sessions = self.hooks.load_project_sessions(project.name)
        start_ids = self.project_autostart_engineer_ids(project, ensure_monitor=ensure_monitor)
        for engineer_id in start_ids:
            if engineer_id in sessions:
                self.start_engineer(sessions[engineer_id], reset=reset)
        if (
            ensure_monitor
            and project.window_mode != "tabs-1up"
            and (reset or not self.hooks.tmux_has_session(project.monitor_session))
        ):
            self._start_monitor_with_retry(project, sessions, reset=reset)

    def seat_requires_launch_confirmation(self, project: Any, engineer_id: str) -> bool:
        engineer_map, _ = self.project_engineer_context(project)
        engineer = engineer_map.get(engineer_id)
        if engineer is None:
            return True
        return not (engineer.patrol_authority and engineer.remind_active_loop_owner)

    def _start_monitor_with_retry(self, project: Any, sessions: dict[str, Any], *, reset: bool) -> None:
        last_error: SessionStartError | None = None
        for attempt in range(1, TMUX_COMMAND_RETRIES + 1):
            try:
                if reset and self.hooks.tmux_has_session(project.monitor_session):
                    self._run_tmux_with_retry(
                        ["kill-session", "-t", project.monitor_session],
                        reason=f"recycle monitor session {project.monitor_session}",
                        check=False,
                    )
                if self.hooks.tmux_has_session(project.monitor_session):
                    # Re-run layout from scratch to avoid partial state.
                    self._run_tmux_with_retry(
                        ["kill-session", "-t", project.monitor_session],
                        reason=f"rebuild monitor session {project.monitor_session}",
                        check=False,
                    )
                self.hooks.build_monitor_layout(project, sessions)
                if not self.hooks.tmux_has_session(project.monitor_session):
                    raise SessionStartError(
                        f"monitor session {project.monitor_session} missing after layout build"
                    )
                # Verify monitor session contains at least one pane.
                monitor_state = self._session_window_state(project.monitor_session)
                if ", panes=empty" in monitor_state:
                    raise SessionStartError(f"monitor session empty after layout build: {monitor_state}")
                return
            except Exception as exc:
                wrapped_error = exc if isinstance(exc, SessionStartError) else SessionStartError(str(exc))
                window_state = self._session_window_state(project.monitor_session)
                last_error = SessionStartError(
                    f"monitor session '{project.monitor_session}' error={wrapped_error}; window_state={window_state}"
                )
                if self.hooks.tmux_has_session(project.monitor_session):
                    self._run_tmux_with_retry(
                        ["kill-session", "-t", project.monitor_session],
                        reason=f"cleanup monitor session {project.monitor_session}",
                        check=False,
                    )
                if attempt < TMUX_COMMAND_RETRIES:
                    print(
                        f"start_monitor_retry: project={project.name} attempt={attempt}/{TMUX_COMMAND_RETRIES}",
                        file=sys.stderr,
                    )
                    time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)
                    continue
        raise SessionStartError(
            f"start monitor for {project.name} failed after {TMUX_COMMAND_RETRIES} attempts; reason={last_error}"
        ) from last_error
