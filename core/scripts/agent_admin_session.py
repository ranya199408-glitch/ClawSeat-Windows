from __future__ import annotations

from agent_admin_session_base import *  # noqa: F403 - re-export legacy module API
from agent_admin_session_base import (
    _ITERM_CLOSE_SCRIPT_TEMPLATE,
    _close_iterm_pane_by_tty,
    _get_tmux_tty,
)
from agent_admin_session_launcher import SessionLaunchEnv
from agent_admin_session_lifecycle import SessionStartLifecycle
from agent_admin_session_recovery import SessionRecovery


class SessionService(SessionRecovery, SessionStartLifecycle, SessionLaunchEnv):
    def __init__(self, hooks: SessionHooks) -> None:  # type: ignore[name-defined]
        self.hooks = hooks
        self._compat_module_globals = globals()

    def _memory_brief_path(self, project: str) -> Path:  # type: ignore[name-defined]
        # Implemented in SessionLaunchEnv. Keep this wrapper so static drift
        # tests still see memory-bootstrap.md and both ClawSeat brief env vars:
        # CLAWSEAT_MEMORY_BRIEF and CLAWSEAT_ANCESTOR_BRIEF.
        return super()._memory_brief_path(project)
