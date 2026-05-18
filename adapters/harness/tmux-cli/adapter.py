from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

CLAWSEAT_ROOT = Path(
    os.environ.get("CLAWSEAT_ROOT", str(Path(__file__).resolve().parents[3]))
)
CORE_ROOT = CLAWSEAT_ROOT / "core"

from core.resolve import resolve_clawseat_root as _shared_resolve_clawseat_root
from core.lib.real_home import real_user_home
from core.harness_adapter import (
    AuthConfig,
    HarnessAdapter,
    RecoverResult,
    ResumeResult,
    SeatObservable,
    SeatPlan,
    SendResult,
    SessionHandle,
    SessionState,
)

AUTH_KEYWORDS = (
    "sign in",
    "oauth",
    "login successful",
    "paste code here",
    "api key",
    "authentication",
)
ONBOARDING_KEYWORDS = (
    "quick safety check",
    "accessing workspace",
    "bypass permissions",
    "/theme",
    "onboarding",
)
DEGRADED_KEYWORDS = (
    "traceback",
    "exception",
    "error:",
    "retry",
    "forbidden",
    "rate limit",
    "exceeded retry",
    "usage limit",
    "crash",
)
READY_KEYWORDS = ("ready", "idle", "waiting for input", "bypass permissions on")
TMUX_COMMAND_RETRIES = 2
TMUX_COMMAND_TIMEOUT_SECONDS = 8.0
TMUX_COMMAND_RETRY_DELAY_SECONDS = 1.0
SEND_AND_VERIFY_SH = str(CORE_ROOT / "shell-scripts" / "send-and-verify.sh")

# Input-reason detection
# (keywords, reason) — checked in order; first match wins
_INPUT_REASON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("rate limit", "exceeded retry", "usage limit", "quota exceeded", "too many requests"), "rate_limit"),
    (("sign in", "api key", "oauth", "authentication", "paste code here"), "auth_prompt"),
    (("what would you like", "which would you prefer", "how should i", "should i"), "user_question"),
    (("?", "press enter to continue", "press return", "continue?", "proceed?"), "idle_prompt"),
)

# Sub-reasons for DEGRADED state — used to distinguish authz (403) vs quota (429)
AUTHZ_DEGRADED_KEYWORDS = ("forbidden", "access forbidden", "permission denied", "unauthorized")
QUOTA_DEGRADED_KEYWORDS = ("rate limit", "exceeded retry", "usage limit", "quota exceeded", "too many requests")


class TmuxCliAdapter(HarnessAdapter):
    def __init__(
        self,
        *,
        agents_root: str | Path | None = None,
        sessions_root: str | Path | None = None,
        workspaces_root: str | Path | None = None,
    ) -> None:
        inferred_agents_root = self._default_agents_root()
        home = real_user_home()
        self.agents_root = Path(
            agents_root or os.environ.get("AGENTS_ROOT", str(inferred_agents_root or (home / ".agents")))
        ).expanduser()
        self.clawseat_root = self._resolve_clawseat_root(self.agents_root)
        self.sessions_root = Path(
            sessions_root or os.environ.get("SESSIONS_ROOT", str(self.agents_root / "sessions"))
        ).expanduser()
        self.workspaces_root = Path(
            workspaces_root or os.environ.get("WORKSPACES_ROOT", str(self.agents_root / "workspaces"))
        ).expanduser()
        self.agent_admin = None
        self.harness_common = None
        self._last_probe_reason: str | None = None  # set by probe_state_detailed
        self.send_strategies = self._parse_message_strategies(
            os.environ.get("CLAWSEAT_MESSAGE_STRATEGY", "send-and-verify")
        )

    def _classify_degraded_reason(self, output: str) -> str | None:
        """
        Classify the sub-reason for a DEGRADED state.

        Returns 'authz' for 403/forbidden issues, 'quota' for 429/rate-limit issues,
        or None if the cause is ambiguous/generic.
        """
        lowered = output.lower()
        if any(kw in lowered for kw in AUTHZ_DEGRADED_KEYWORDS):
            return "authz"
        if any(kw in lowered for kw in QUOTA_DEGRADED_KEYWORDS):
            return "quota"
        return None

    def probe_state_detailed(self, handle: SessionHandle) -> tuple[SessionState, str | None, SeatObservable]:
        """
        Probe session state with sub-reason classification and observable metadata.

        Returns (state, reason, observable) where:
        - state  : SessionState enum
        - reason : 'authz' (403/forbidden) | 'quota' (429/rate-limit) | None
        - observable : SeatObservable with current_task_id, needs_input, input_reason,
                       last_prompt_excerpt
        """
        output = self.get_output(handle, lines=80)
        state = self.probe_state(handle)
        reason: str | None = None
        if state == SessionState.DEGRADED:
            reason = self._classify_degraded_reason(output)
        self._last_probe_reason = reason
        observable = self._extract_observable(output, handle.project)
        return state, reason, observable

    def _extract_observable(self, output: str, project: str) -> SeatObservable:
        """
        Extract observability fields from pane output.

        - current_task_id   : matches task_id from TODO.md lines or [project] TASK-XXX patterns,
                              including IDs without numeric middle segments
        - needs_input       : True when pane appears to be waiting at a prompt
        - input_reason      : rate_limit | auth_prompt | idle_prompt | user_question | ""
        - last_prompt_excerpt: last 3 non-empty lines of output
        """
        import re

        task_id = ""
        task_id_pattern = r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+"
        for line in output.splitlines():
            line = line.strip()
            m = re.search(rf"task_id[:\s]+({task_id_pattern})", line, re.IGNORECASE)
            if m:
                task_id = m.group(1)
                break
            m = re.search(r"\[" + re.escape(project) + r"\]\s+(" + task_id_pattern + r")", line, re.IGNORECASE)
            if m:
                task_id = m.group(1)
                break

        # Detect needs_input from last few lines
        non_empty = [l.strip() for l in output.splitlines() if l.strip()]
        tail = non_empty[-5:] if non_empty else []
        last_excerpt = " | ".join(tail[-3:]) if tail else ""

        needs_input = False
        input_reason = ""
        lowered = output.lower()

        for keywords, reason in _INPUT_REASON_RULES:
            if any(kw in lowered for kw in keywords):
                needs_input = True
                input_reason = reason
                break

        # Also flag needs_input if last non-empty line ends with "?" and suggests waiting
        if not needs_input and tail:
            last_line = tail[-1]
            if last_line.endswith("?") and any(
                k in last_line.lower() for k in ("continue", "proceed", "what", "which", "how")
            ):
                needs_input = True
                input_reason = "user_question"

        return SeatObservable(
            current_task_id=task_id,
            needs_input=needs_input,
            input_reason=input_reason,
            last_prompt_excerpt=last_excerpt,
        )

    @staticmethod
    def _parse_message_strategies(raw: str) -> tuple[str, ...]:
        candidates = [value.strip() for value in raw.split(",") if value.strip()]
        if not candidates:
            return ("send-and-verify",)
        normalized: list[str] = []
        invalid: list[str] = []
        for value in candidates:
            if value == "send-and-verify":
                normalized.append(value)
            else:
                invalid.append(value)
        if invalid:
            print(
                f"tmux_adapter: unsupported CLAWSEAT_MESSAGE_STRATEGY values ignored: {', '.join(invalid)}",
                file=sys.stderr,
            )
        if not normalized:
            return ("send-and-verify",)
        return tuple(dict.fromkeys(normalized))

    def materialize(self, plan: SeatPlan) -> SessionHandle:
        workspace_path = Path(plan.workspace_path).expanduser()
        workspace_path.mkdir(parents=True, exist_ok=True)

        session_binding = dict(plan.session_binding_spec)
        session_name = str(session_binding.get("session_name", f"{plan.project}-{plan.seat_id}-{plan.tool}"))
        session_path = Path(
            str(
                session_binding.get(
                    "session_path",
                    self.sessions_root / plan.project / plan.seat_id / "session.toml",
                )
            )
        ).expanduser()
        contract_path = Path(
            str(session_binding.get("contract_path", workspace_path / "WORKSPACE_CONTRACT.toml"))
        ).expanduser()
        workspace_binding_path = Path(
            str(session_binding.get("workspace_binding_path", workspace_path / "SESSION_BINDING.toml"))
        ).expanduser()

        session_binding.setdefault("version", 1)
        session_binding.setdefault("project", plan.project)
        session_binding.setdefault("engineer_id", plan.seat_id)
        session_binding.setdefault("tool", plan.tool)
        session_binding.setdefault("role", plan.role)
        session_binding.setdefault("workspace", str(workspace_path))
        session_binding["session"] = session_name
        session_binding["session_name"] = session_name
        session_binding["contract_path"] = str(contract_path)
        session_binding["session_path"] = str(session_path)
        session_binding["workspace_binding_path"] = str(workspace_binding_path)

        self._write_toml(contract_path, plan.contract_content)
        self._write_toml(session_path, session_binding)
        self._write_toml(workspace_binding_path, session_binding)

        return self._make_handle(
            seat_id=plan.seat_id,
            project=plan.project,
            tool=plan.tool,
            runtime_id=session_name,
            workspace_path=str(workspace_path),
            session_path=str(session_path),
        )

    def start_session(self, seat_id: str, project: str, plan: SeatPlan) -> SessionHandle:
        self._ensure_helpers()
        handle = self.materialize(plan)
        session = self.agent_admin.load_session(project, seat_id)
        self.agent_admin.session_start_engineer(session)
        return handle

    def stop_session(self, handle: SessionHandle) -> None:
        self._ensure_helpers()
        if not self._session_exists(handle.runtime_id):
            return
        session = self.agent_admin.load_session(handle.project, handle.seat_id)
        self.agent_admin.session_stop_engineer(session)

    def destroy_session(self, handle: SessionHandle) -> None:
        if self._session_exists(handle.runtime_id):
            self._run(["kill-session", "-t", handle.runtime_id], "destroy session")

    def resume_session(self, handle: SessionHandle) -> ResumeResult:
        if not self._session_exists(handle.runtime_id):
            return ResumeResult(resumed=False, state=SessionState.DEAD, detail="runtime is not running")
        send_result = self.send_message(handle, "继续")
        state = self.probe_state(handle)
        return ResumeResult(
            resumed=send_result.delivered,
            state=state,
            detail=send_result.detail,
        )

    def recover_session(self, handle: SessionHandle) -> RecoverResult:
        self._ensure_helpers()
        if self._session_exists(handle.runtime_id):
            resumed = self.resume_session(handle)
            return RecoverResult(
                recovered=resumed.resumed,
                resumed=resumed.resumed,
                restarted=False,
                state=resumed.state,
                detail=resumed.detail,
            )
        session = self.agent_admin.load_session(handle.project, handle.seat_id)
        self.agent_admin.session_start_engineer(session)
        state = self.probe_state(handle)
        return RecoverResult(
            recovered=state is not SessionState.DEAD,
            resumed=False,
            restarted=True,
            state=state,
            detail="started session via agent_admin.session_start_engineer",
        )

    def send_message(self, handle: SessionHandle, text: str) -> SendResult:
        return self._send_message_send_and_verify(handle, text)

    def get_output(self, handle: SessionHandle, lines: int = 50) -> str:
        self._ensure_helpers()
        if not self._session_exists(handle.runtime_id):
            return ""
        try:
            profile = self._profile_for_handle(handle)
        except FileNotFoundError:
            # Handle case where session binding doesn't exist yet (tmux fallback handles)
            workspace = Path(handle.workspace_path).expanduser() if handle.workspace_path else Path.cwd()
            profile = SimpleNamespace(
                workspace_root=workspace,
                project_name=handle.project,
                repo_root=workspace,
            )
        return self.harness_common.capture_session_pane(profile, handle.seat_id, lines=max(lines, 1))

    def probe_state(self, handle: SessionHandle) -> SessionState:
        if not self._session_exists(handle.runtime_id):
            return SessionState.DEAD
        output = self.get_output(handle, lines=80)
        lowered = output.lower()
        if any(keyword in lowered for keyword in AUTH_KEYWORDS):
            return SessionState.AUTH_NEEDED
        if any(keyword in lowered for keyword in DEGRADED_KEYWORDS):
            return SessionState.DEGRADED
        if any(keyword in lowered for keyword in ONBOARDING_KEYWORDS):
            return SessionState.ONBOARDING

        nonempty = [line.strip() for line in output.splitlines() if line.strip()]
        tail = nonempty[-5:]
        if any(keyword in lowered for keyword in READY_KEYWORDS):
            return SessionState.READY
        if any(line.startswith("❯") or line.startswith(">") or line.startswith("$") for line in tail):
            return SessionState.READY
        return SessionState.RUNNING

    def list_sessions(self, project: str) -> list[SessionHandle]:
        handles: list[SessionHandle] = []
        project_root = self.sessions_root / project
        if project_root.exists():
            for session_path in sorted(project_root.glob("*/session.toml")):
                binding = self._read_toml(session_path)
                session_name = str(binding.get("session", binding.get("session_name", ""))).strip()
                tool = str(binding.get("tool", "")).strip()
                workspace = str(binding.get("workspace", "")).strip()
                handles.append(
                    self._make_handle(
                        seat_id=str(binding.get("engineer_id", session_path.parent.name)).strip(),
                        project=project,
                        tool=tool,
                        runtime_id=session_name,
                        workspace_path=workspace,
                        session_path=str(session_path),
                    )
                )
            if handles:
                return handles

        result = self._run_tmux_with_retry(["list-sessions", "-F", "#{session_name}"], "list-sessions")
        prefix = f"{project}-"
        for raw in result.stdout.splitlines():
            session_name = raw.strip()
            if not session_name.startswith(prefix):
                continue
            remainder = session_name[len(prefix) :]
            if "-" not in remainder:
                continue
            seat_id, tool = remainder.rsplit("-", 1)
            fallback_session_path = str(self.sessions_root / project / seat_id / "session.toml")
            handles.append(
                self._make_handle(
                    seat_id=seat_id,
                    project=project,
                    tool=tool,
                    runtime_id=session_name,
                    session_path=fallback_session_path,
                )
            )
        return handles

    def get_auth_config(self, seat_id: str, project: str) -> AuthConfig:
        session_path = self.sessions_root / project / seat_id / "session.toml"
        if not session_path.exists():
            return AuthConfig(
                seat_id=seat_id,
                project=project,
                auth_mode="",
                provider="",
                identity="",
            )
        binding = self._read_toml(session_path)
        return AuthConfig(
            seat_id=seat_id,
            project=project,
            auth_mode=str(binding.get("auth_mode", "")),
            provider=str(binding.get("provider", "")),
            identity=str(binding.get("identity", "")),
            secret_file=str(binding.get("secret_file", "")),
            runtime_dir=str(binding.get("runtime_dir", "")),
            locator={
                "session_path": str(session_path),
                "runtime_id": str(binding.get("session", binding.get("session_name", ""))),
            },
        )

    def _session_exists(self, runtime_id: str) -> bool:
        try:
            self._run_tmux_with_retry(["has-session", "-t", runtime_id], "has-session")
        except RuntimeError:
            return False
        return True

    def _load_session_binding(
        self,
        handle: SessionHandle,
        *,
        required: bool = True,
    ) -> dict[str, Any]:
        session_path = Path(handle.session_path).expanduser() if handle.session_path else Path()
        if not handle.session_path and handle.project and handle.seat_id:
            session_path = self.sessions_root / handle.project / handle.seat_id / "session.toml"
        if not session_path.exists():
            if required:
                raise FileNotFoundError(f"session binding missing: {session_path}")
            return {}
        return self._read_toml(session_path)

    def _read_toml(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            return tomllib.load(handle)

    def _run(self, args: list[str], label: str) -> None:
        result = self._run_tmux_with_retry(args, label)
        if result.returncode == 0:
            return
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"{label} failed: {detail}")

    def _run_tmux_with_retry(self, args: list[str], label: str) -> subprocess.CompletedProcess:
        last: subprocess.CompletedProcess | None = None
        for attempt in range(1, TMUX_COMMAND_RETRIES + 1):
            try:
                tmux_bin = self._resolve_tmux_bin()
                result = subprocess.run(
                    [tmux_bin, *args],
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=TMUX_COMMAND_TIMEOUT_SECONDS,
                )
                if result.returncode == 0:
                    return result
                last = result
                if attempt < TMUX_COMMAND_RETRIES:
                    print(
                        f"tmux_retry: {label} attempt={attempt}/{TMUX_COMMAND_RETRIES} rc={result.returncode}",
                        file=sys.stderr,
                    )
                    time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)
            except subprocess.TimeoutExpired as exc:
                if attempt >= TMUX_COMMAND_RETRIES:
                    raise RuntimeError(f"{label} timed out after {TMUX_COMMAND_RETRIES} attempts: {exc}") from exc
                print(
                    f"tmux_retry: {label} attempt={attempt}/{TMUX_COMMAND_RETRIES} timeout={TMUX_COMMAND_TIMEOUT_SECONDS}s",
                    file=sys.stderr,
                )
                time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)
            except OSError as exc:
                if attempt >= TMUX_COMMAND_RETRIES:
                    raise RuntimeError(f"{label} failed before executing tmux: {exc}") from exc
                print(
                    f"tmux_retry: {label} attempt={attempt}/{TMUX_COMMAND_RETRIES} OSError={exc}",
                    file=sys.stderr,
                )
                time.sleep(TMUX_COMMAND_RETRY_DELAY_SECONDS)
        if last is None:
            raise RuntimeError(f"{label} failed with no tmux result")
        detail = last.stderr.strip() or last.stdout.strip() or f"exit {last.returncode}"
        raise RuntimeError(f"{label} failed after {TMUX_COMMAND_RETRIES} attempts: {detail}")

    def _resolve_tmux_bin(self) -> str:
        explicit = os.environ.get("TMUX_BIN")
        if explicit:
            return explicit
        env_tmux = shutil.which("tmux")
        if env_tmux:
            return env_tmux
        for candidate in ("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/usr/bin/tmux", "/bin/tmux"):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return candidate
        raise RuntimeError("tmux binary not found in PATH or fallback locations")

    def _send_and_verify(self, handle: SessionHandle, text: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [SEND_AND_VERIFY_SH, "--project", handle.project, handle.seat_id, text],
            text=True,
            capture_output=True,
            check=False,
            timeout=TMUX_COMMAND_TIMEOUT_SECONDS + 8,
        )

    def _send_message_send_and_verify(self, handle: SessionHandle, text: str) -> SendResult:
        try:
            result = self._send_and_verify(handle, text)
        except FileNotFoundError:
            return SendResult(
                delivered=False,
                transport="send-and-verify",
                detail=f"send-and-verify missing at {SEND_AND_VERIFY_SH}",
            )
        except subprocess.TimeoutExpired as exc:
            return SendResult(
                delivered=False,
                transport="send-and-verify",
                detail=f"send-and-verify timeout: {exc}",
            )

        output = (result.stdout or "").strip()
        if result.returncode == 0 and (output.startswith("SENT:") or "OK" in output):
            return SendResult(delivered=True, transport="send-and-verify", detail=output)
        if "RETRY_FAILED" in output:
            reason = "message may not have been submitted (input still present after Enter retry)"
        elif "RETRY_ENTER_FAILED" in output:
            reason = "send-and-verify retry Enter failed before queue submission"
        elif "RETRY_NEEDED" in output:
            reason = "send-and-verify retried Enter after stale input echo"
        elif "CAPTURE_AFTER_FAILED" in output or "CAPTURE_BEFORE_FAILED" in output:
            reason = f"send-and-verify capture verification failed: {output}"
        else:
            reason = (output or result.stderr or f"exit {result.returncode}").strip()
        return SendResult(
            delivered=False,
            transport="send-and-verify",
            detail=reason,
        )

    def _write_toml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render_toml_dict(data).rstrip() + "\n", encoding="utf-8")

    def _default_agents_root(self) -> Path | None:
        cwd = Path.cwd().resolve()
        for parent in (cwd, *cwd.parents):
            if parent.name == ".agents":
                return parent
        return None

    def _load_helpers(self) -> None:
        agent_admin_root = self.clawseat_root / "core" / "scripts"
        harness_root = self.clawseat_root / "core" / "skills" / "gstack-harness" / "scripts"
        for path in (agent_admin_root, harness_root):
            path_str = str(path)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)
        import agent_admin  # type: ignore
        import _common as harness_common  # type: ignore

        self.agent_admin = agent_admin
        self.harness_common = harness_common

    def _ensure_helpers(self) -> None:
        if self.agent_admin is not None and self.harness_common is not None:
            return
        self._load_helpers()

    def _resolve_clawseat_root(self, agents_root: Path) -> Path:
        return _shared_resolve_clawseat_root(agents_root)

    def _profile_for_handle(self, handle: SessionHandle) -> Any:
        binding = self._load_session_binding(handle)
        workspace = Path(str(binding.get("workspace", handle.workspace_path or ""))).expanduser()
        workspace_root = workspace.parent if workspace.name == handle.seat_id else Path(str(handle.workspace_path)).expanduser().parent
        repo_root = Path(str(binding.get("repo_root", Path.cwd()))).expanduser()
        return SimpleNamespace(
            workspace_root=workspace_root,
            project_name=handle.project,
            repo_root=repo_root,
        )

    def _make_handle(
        self,
        *,
        seat_id: str,
        project: str,
        tool: str,
        runtime_id: str,
        workspace_path: str = "",
        session_path: str = "",
    ) -> SessionHandle:
        return SessionHandle(
            seat_id=seat_id,
            project=project,
            tool=tool,
            runtime_id=runtime_id,
            locator={
                "runtime_id": runtime_id,
                "transport": "tmux",
                "workspace_path": workspace_path,
                "session_path": session_path,
            },
            workspace_path=workspace_path,
            session_path=session_path,
        )

    def _render_toml_dict(self, data: dict[str, Any], prefix: str = "") -> str:
        lines: list[str] = []
        nested: list[tuple[str, dict[str, Any]]] = []
        for key, value in data.items():
            if isinstance(value, dict):
                nested.append((key, value))
                continue
            lines.append(f"{key} = {self._render_toml_value(value)}")
        for key, value in nested:
            section = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            if lines:
                lines.append("")
            lines.append(f"[{section}]")
            nested_text = self._render_toml_dict(value, prefix=section)
            if nested_text:
                lines.append(nested_text)
        return "\n".join(lines)

    def _render_toml_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return repr(value)
        if isinstance(value, list):
            return "[" + ", ".join(self._render_toml_value(item) for item in value) + "]"
        return json.dumps(str(value), ensure_ascii=False)
