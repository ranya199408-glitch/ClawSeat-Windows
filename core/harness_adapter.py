from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionState(Enum):
    AUTH_NEEDED = "auth_needed"
    ONBOARDING = "onboarding"
    RUNNING = "running"
    READY = "ready"
    DEGRADED = "degraded"
    DEAD = "dead"


@dataclass(slots=True)
class SeatPlan:
    seat_id: str
    project: str
    role: str
    tool: str
    workspace_path: str
    contract_content: dict[str, Any]
    session_binding_spec: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionHandle:
    seat_id: str
    project: str
    tool: str
    runtime_id: str
    locator: dict[str, Any] = field(default_factory=dict)
    workspace_path: str = ""
    session_path: str = ""


@dataclass(slots=True)
class ResumeResult:
    resumed: bool
    state: SessionState
    detail: str = ""


@dataclass(slots=True)
class RecoverResult:
    recovered: bool
    resumed: bool
    restarted: bool
    state: SessionState
    detail: str = ""


@dataclass(slots=True)
class SendResult:
    delivered: bool
    transport: str
    detail: str = ""


@dataclass(slots=True)
class AuthConfig:
    seat_id: str
    project: str
    auth_mode: str
    provider: str
    identity: str
    secret_file: str = ""
    runtime_dir: str = ""
    locator: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SeatObservable:
    """Extended observability fields for a seat session."""

    current_task_id: str = ""
    needs_input: bool = False
    input_reason: str = ""  # rate_limit | auth_prompt | idle_prompt | user_question | ""
    last_prompt_excerpt: str = ""


class HarnessAdapter(ABC):
    # Abstract surface. ABC already enforces subclass implementation at
    # instantiation time, so these bodies are pure contracts — `...`
    # reads as "no default behavior" without the redundant
    # `raise NotImplementedError` that static type checkers flagged
    # (audit L2). If a subclass forgets a method, Python raises
    # ``TypeError: Can't instantiate abstract class ... with abstract
    # method ...`` at construction, which is clearer than a runtime
    # NotImplementedError from an actual call.

    @abstractmethod
    def materialize(self, plan: SeatPlan) -> SessionHandle: ...

    @abstractmethod
    def start_session(self, seat_id: str, project: str, plan: SeatPlan) -> SessionHandle: ...

    @abstractmethod
    def stop_session(self, handle: SessionHandle) -> None: ...

    @abstractmethod
    def destroy_session(self, handle: SessionHandle) -> None: ...

    @abstractmethod
    def resume_session(self, handle: SessionHandle) -> ResumeResult: ...

    @abstractmethod
    def recover_session(self, handle: SessionHandle) -> RecoverResult: ...

    @abstractmethod
    def send_message(self, handle: SessionHandle, text: str) -> SendResult: ...

    @abstractmethod
    def get_output(self, handle: SessionHandle, lines: int = 50) -> str: ...

    @abstractmethod
    def probe_state(self, handle: SessionHandle) -> SessionState: ...

    @abstractmethod
    def list_sessions(self, project: str) -> list[SessionHandle]: ...

    @abstractmethod
    def get_auth_config(self, seat_id: str, project: str) -> AuthConfig: ...
