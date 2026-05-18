from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Callable

from agent_admin_crud_base import require_caller_authority
import agent_admin_window as window_ops


_RESUME_DEDUPE_WINDOW_SECONDS = 30
projects_registry = None
real_user_home = None


@dataclass
class CommandHooks:
    error_cls: type[Exception]
    load_project_or_current: Callable[[str | None], Any]
    resolve_engineer_session: Callable[..., Any]
    provision_session_heartbeat: Callable[..., tuple[bool, str]]
    load_project_sessions: Callable[[str], dict[str, Any]]
    tmux_has_session: Callable[[str], bool]
    load_projects: Callable[[], dict[str, Any]]
    get_current_project_name: Callable[[dict[str, Any]], str | None]
    session_service: Any
    open_monitor_window: Callable[[Any, dict[str, Any], dict[str, Any]], None]
    open_dashboard_window: Callable[[list[Any]], None]
    open_project_tabs_window: Callable[[Any, dict[str, Any], dict[str, Any]], None]
    open_engineer_window: Callable[[Any, Any | None], None]
    load_engineers: Callable[[], dict[str, Any]]
    write_project: Callable[[Any], None] | None = None
    write_session: Callable[[Any], None] | None = None
    session_path: Callable[[str, str], Path] | None = None
    archive_if_exists: Callable[[Path, str], None] | None = None
    identity_name: Callable[..., str] | None = None
    runtime_dir_for_identity: Callable[..., Path] | None = None
    secret_file_for: Callable[..., Path] | None = None
    session_name_for: Callable[..., str] | None = None
    workspaces_root: Path | None = None
    ensure_dir: Callable[[Path], None] | None = None
    ensure_secret_permissions: Callable[[Path], None] | None = None


class CommandHandlers:
    def __init__(self, hooks: CommandHooks) -> None:
        self.hooks = hooks

    def _session_supports_heartbeat_provisioning(self, session: Any) -> bool:
        return str(getattr(session, "tool", "") or "") == "claude"

    def _require_dispatch_authority(self, action: str) -> None:
        require_caller_authority("dispatch", action, self.hooks.error_cls)

    def _validate_project_seat_override(self, session: Any, *, accept_override: bool = False) -> None:
        project_name = str(getattr(session, "project", "") or "").strip()
        engineer_id = str(getattr(session, "engineer_id", "") or "").strip()
        if not project_name or not engineer_id:
            return
        project = self.hooks.load_project_or_current(project_name)
        overrides = getattr(project, "seat_overrides", None) or {}
        if not isinstance(overrides, dict):
            return
        override = overrides.get(engineer_id)
        if not isinstance(override, dict) or not override:
            return
        fields = ("tool", "auth_mode", "provider")
        for field in fields:
            expected = str(override.get(field, "") or "").strip()
            if not expected:
                continue
            actual = str(getattr(session, field, "") or "").strip()
            if expected == actual:
                continue
            message = (
                f"project.toml seat_override requires {field}={expected} "
                f"but got {field}={actual or '<unset>'}. "
                "Use --accept-override to bypass."
            )
            if accept_override:
                print(f"warn: {message}", file=sys.stderr)
                return
            raise self.hooks.error_cls(f"error: {message}")

    def _touch_project(self, project_name: str) -> None:
        try:
            registry = projects_registry
            if registry is None:
                import projects_registry as registry

            registry.touch_project(project_name)
        except Exception as exc:
            print(f"projects registry touch skipped: {exc}", file=sys.stderr)

    def _provision_session_heartbeat_if_supported(self, session: Any) -> None:
        if not self._session_supports_heartbeat_provisioning(session):
            return
        try:
            _provisioned, detail = self.hooks.provision_session_heartbeat(session)
            if detail:
                print(detail)
        except Exception as exc:
            print(f"heartbeat: {exc}")

    def _resume_state_dir(self) -> Path:
        resolver = real_user_home
        if resolver is None:
            core_lib = Path(__file__).resolve().parents[1] / "lib"
            if str(core_lib) not in sys.path:
                sys.path.insert(0, str(core_lib))
            from real_home import real_user_home as resolver

        return resolver() / ".agent-runtime" / "active"

    def _resume_session_path(self, seat: str) -> Path:
        return self._resume_state_dir() / f"{seat}.session"

    def _resume_stamp_path(self, seat: str) -> Path:
        return self._resume_state_dir() / f"{seat}.resume"

    def _read_active_session_id(self, seat: str) -> str | None:
        try:
            text = self._resume_session_path(seat).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def _resume_recently_seen(self, seat: str) -> bool:
        try:
            age_seconds = time.time() - self._resume_stamp_path(seat).stat().st_mtime
        except OSError:
            return False
        return age_seconds < _RESUME_DEDUPE_WINDOW_SECONDS

    def _mark_resume_seen(self, seat: str, session_id: str | None) -> None:
        stamp = self._resume_stamp_path(seat)
        stamp.parent.mkdir(parents=True, exist_ok=True)
        payload = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        if session_id:
            payload = f"{payload}\n{session_id}\n"
        stamp.write_text(payload, encoding="utf-8")
        try:
            stamp.chmod(0o600)
        except OSError:
            pass

    def _resume_label_for_tool(self, tool: str, session_id: str | None) -> str | None:
        if session_id:
            return session_id
        if tool == "codex":
            return "last"
        if tool == "gemini":
            return "latest"
        return None

    def _resume_command_for_tool(self, session: Any, session_id: str | None) -> list[str]:
        tool = str(getattr(session, "tool", "") or "")
        if tool == "claude":
            return ["claude", "--resume", session_id] if session_id else ["claude"]
        if tool == "codex":
            return ["codex", "--resume", session_id] if session_id else ["codex", "--last"]
        if tool == "gemini":
            return ["gemini", "--resume", "latest"]
        raise self.hooks.error_cls(f"unsupported tool for resume: {tool}")

    def _resume_banner(self, label: str) -> str:
        return f"Resuming session {label} from {datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')}"

    def _tmux_resume_status(self, session: Any) -> tuple[str, str]:
        status_script = Path(__file__).resolve().parents[1] / "shell-scripts" / "check-engineer-status.sh"
        env = dict(os.environ)
        env["AGENT_PROJECT"] = session.project
        try:
            result = subprocess.run(
                ["bash", str(status_script), session.engineer_id],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise self.hooks.error_cls(f"resume status probe failed for {session.session}: {exc}") from exc
        output = (result.stdout or result.stderr or "").strip()
        if not output:
            return ("UNKNOWN", "")
        line = output.splitlines()[-1].strip()
        if ":" in line:
            _seat, tail = line.split(":", 1)
            tail = tail.strip()
        else:
            tail = line
        state = tail.split(" ", 1)[0].strip().upper() if tail else "UNKNOWN"
        return (state, line)

    def _send_tmux_resume_command(self, session: Any, resume_cmd: list[str]) -> None:
        if not resume_cmd:
            raise self.hooks.error_cls(f"resume command missing for {session.session}")
        shell_command = f"cd {shlex.quote(session.workspace)} && exec " + " ".join(
            shlex.quote(part) for part in resume_cmd
        )
        result = subprocess.run(
            ["tmux", "send-keys", "-t", f"={session.session}", shell_command, "Enter"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise self.hooks.error_cls(
                f"resume send-keys failed for {session.session}: {detail or f'exit {result.returncode}'}"
            )

    def _resume_session(self, session: Any, *, fresh: bool) -> None:
        session_id = self._read_active_session_id(session.engineer_id)
        if fresh:
            self.hooks.session_service.start_engineer(session, reset=True)
            self._provision_session_heartbeat_if_supported(session)
            self._touch_project(session.project)
            print(session.session)
            return

        if self._resume_recently_seen(session.engineer_id):
            print(
                f"seat resume: {session.session} no-op (recent resume within 30s)",
                file=sys.stderr,
            )
            return

        if not self.hooks.tmux_has_session(session.session):
            self.hooks.session_service.start_engineer(session, reset=False)
            self._provision_session_heartbeat_if_supported(session)
            self._touch_project(session.project)
            self._mark_resume_seen(session.engineer_id, session_id)
            print(session.session)
            return

        state, line = self._tmux_resume_status(session)
        if state not in {"IDLE", "CRASHED", "SESSION_NOT_FOUND", "EMPTY"}:
            raise self.hooks.error_cls(
                f"seat resume refused for {session.session}: tmux still active ({line or state or 'unknown'})"
            )

        resume_cmd = self._resume_command_for_tool(session, session_id)
        resume_label = self._resume_label_for_tool(str(getattr(session, "tool", "") or ""), session_id)
        if resume_label:
            print(self._resume_banner(resume_label))
        self._send_tmux_resume_command(session, resume_cmd)
        self._touch_project(session.project)
        self._mark_resume_seen(session.engineer_id, session_id)
        print(session.session)

    def session_start_engineer(self, args: Any) -> int:
        self._require_dispatch_authority("session start-engineer")
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        self._validate_project_seat_override(
            session,
            accept_override=bool(getattr(args, "accept_override", False)),
        )
        self.hooks.session_service.start_engineer(session, reset=args.reset)
        self._provision_session_heartbeat_if_supported(session)
        self._touch_project(session.project)
        print(session.session)
        return 0

    def seat_resume(self, args: Any) -> int:
        self._require_dispatch_authority("seat resume")
        seat_id = str(getattr(args, "seat", "") or getattr(args, "engineer", "") or "").strip()
        if not seat_id:
            raise self.hooks.error_cls("seat resume requires a seat id")
        project = self.hooks.load_project_or_current(getattr(args, "project", None))
        session = self.hooks.resolve_engineer_session(seat_id, project_name=project.name)
        self._validate_project_seat_override(session, accept_override=False)
        self._resume_session(session, fresh=bool(getattr(args, "fresh", False)))
        return 0

    def project_resume(self, args: Any) -> int:
        self._require_dispatch_authority("project resume")
        project = self.hooks.load_project_or_current(getattr(args, "project", None))
        failures: list[str] = []
        seat_ids = list(getattr(project, "engineers", []) or [])
        for seat_id in seat_ids:
            session = self.hooks.resolve_engineer_session(seat_id, project_name=project.name)
            try:
                self._validate_project_seat_override(session, accept_override=False)
                self._resume_session(session, fresh=bool(getattr(args, "fresh", False)))
            except Exception as exc:  # noqa: BLE001 - summarize per-seat failures
                failures.append(f"{seat_id}: {exc}")
                print(f"project resume: {seat_id} FAILED — {exc}", file=sys.stderr)
        if failures:
            raise self.hooks.error_cls(
                f"project resume failed for {project.name}: {len(failures)}/{len(seat_ids)} seats failed: "
                + "; ".join(failures)
            )
        return 0

    def session_reseed_sandbox(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(getattr(args, "project", None))
        engineer_ids = list(getattr(args, "engineers", []) or [])
        if getattr(args, "all", False):
            engineer_ids = list(project.engineers)
        if not engineer_ids:
            raise self.hooks.error_cls(
                "session reseed-sandbox requires --all or one or more engineer ids"
            )

        changed: list[str] = []
        for engineer_id in engineer_ids:
            session = self.hooks.resolve_engineer_session(engineer_id, project_name=project.name)
            try:
                updated = self.hooks.session_service.reseed_sandbox_user_tool_dirs(session)
            except Exception as exc:  # noqa: BLE001 - surface a readable CLI error
                raise self.hooks.error_cls(
                    f"reseed-sandbox failed for {session.session}: {exc}"
                ) from exc
            if updated:
                changed.append(f"{session.engineer_id}: {', '.join(updated)}")

        if changed:
            print("\n".join(changed))
        else:
            print(f"no sandbox tool dirs needed reseed for {project.name}")
        return 0

    def tmux_clean_stale_clients(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(getattr(args, "project", None))
        project_sessions = self.hooks.load_project_sessions(project.name)
        ordered_sessions: list[Any] = []
        seen: set[str] = set()
        for engineer_id in list(getattr(project, "engineers", []) or []):
            if engineer_id in seen:
                continue
            session = project_sessions.get(engineer_id)
            if session is None:
                continue
            ordered_sessions.append(session)
            seen.add(engineer_id)
        for engineer_id in sorted(project_sessions):
            if engineer_id in seen:
                continue
            ordered_sessions.append(project_sessions[engineer_id])

        dry_run = bool(getattr(args, "dry_run", False))
        total_candidates = 0
        total_whitelist_hits = 0
        total_skip_count = 0
        total_sessions = 0

        if not ordered_sessions:
            print(
                f"tmux clean-stale-clients: project={project.name} sessions=0 "
                f"candidates=0 whitelist_hits=0 skip_count=0 dry_run={int(dry_run)}"
            )
            return 0

        for session in ordered_sessions:
            try:
                report = self.hooks.session_service.clean_stale_attach_clients_report(
                    session.session,
                    dry_run=dry_run,
                )
                self.hooks.session_service.clean_stale_attach_clients(
                    session.session,
                    dry_run=dry_run,
                    report=report,
                )
            except Exception as exc:  # noqa: BLE001 - surface a readable CLI error
                raise self.hooks.error_cls(
                    f"tmux clean-stale-clients failed for {session.session}: {exc}"
                ) from exc

            candidate_count = len(report.candidate_pids)
            whitelist_hits = report.whitelist_hit_count
            skip_count = report.skip_count
            total_candidates += candidate_count
            total_whitelist_hits += whitelist_hits
            total_skip_count += skip_count
            total_sessions += 1
            print(
                f"tmux clean-stale-clients: session={session.session} "
                f"candidates={candidate_count} whitelist_hits={whitelist_hits} "
                f"skip_count={skip_count} dry_run={int(dry_run)}"
            )

        print(
            f"tmux clean-stale-clients: project={project.name} sessions={total_sessions} "
            f"candidates={total_candidates} whitelist_hits={total_whitelist_hits} "
            f"skip_count={total_skip_count} dry_run={int(dry_run)}"
        )
        return 0

    def session_batch_start_engineer(self, args: Any) -> int:
        """Atomically start N seats: parallel tmux, then single iTerm window.

        Replaces the shell idiom `for seat in ...; do session start-engineer
        $seat &; done; wait; window open-monitor <project>` — which is easy
        to get wrong (forgetting `wait` races Phase 2 against Phase 1's
        still-starting tmux sessions, causing open_project_tabs_window to
        skip not-yet-ready seats and leaving partial tabs).

        Phase 1 uses a thread pool so concurrent start_engineer calls share
        Python process state (no subprocess-to-subprocess coordination).
        start_engineer itself is per-seat in every mutation (per-seat
        session.toml, per-seat workspace, per-seat tmux session name) so
        running it in parallel is safe.

        Phase 2 is a single `open_monitor_window` call — one osascript, one
        atomic AppleScript block. No concurrency during Phase 2 means no
        iTerm current-window race even without the fix in
        agent_admin_window.py.
        """
        self._require_dispatch_authority("session batch-start-engineer")
        import concurrent.futures
        import sys

        engineer_ids = list(getattr(args, "engineers", []) or [])
        if not engineer_ids:
            raise self.hooks.error_cls(
                "batch-start-engineer requires one or more engineer ids"
            )
        # Dedupe while preserving order so the operator's intent reads
        # left-to-right but we never ask tmux to start the same session twice.
        seen: set[str] = set()
        ordered: list[str] = []
        for eid in engineer_ids:
            if eid not in seen:
                seen.add(eid)
                ordered.append(eid)
        engineer_ids = ordered

        project_name = getattr(args, "project", None)
        reset = bool(getattr(args, "reset", False))
        skip_iterm = bool(getattr(args, "no_iterm", False))

        # Resolve all sessions up front so we fail fast on typos (bad seat
        # id) before we touch tmux. The resolve step also normalises engineer
        # names for downstream hooks.
        sessions_to_start: list[Any] = []
        for eid in engineer_ids:
            sessions_to_start.append(
                self.hooks.resolve_engineer_session(eid, project_name=project_name)
            )
        accept_override = bool(getattr(args, "accept_override", False))
        for session in sessions_to_start:
            self._validate_project_seat_override(session, accept_override=accept_override)

        # Phase 1 — parallel tmux start.
        def _start_one(session: Any) -> tuple[str, Exception | None]:
            try:
                self.hooks.session_service.start_engineer(session, reset=reset)
                return (session.engineer_id, None)
            except Exception as exc:  # noqa: BLE001 - collect, don't abort pool
                return (session.engineer_id, exc)

        failures: list[tuple[str, Exception]] = []
        started: list[Any] = []
        max_workers = min(len(sessions_to_start), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_start_one, s): s for s in sessions_to_start
            }
            # concurrent.futures.wait blocks until every future is done —
            # this IS the `wait` that shell operators had to remember.
            for fut in concurrent.futures.as_completed(futures):
                session = futures[fut]
                _eid, err = fut.result()
                if err is None:
                    started.append(session)
                    print(f"batch-start-engineer: {session.session} started")
                else:
                    failures.append((session.engineer_id, err))
                    print(
                        f"batch-start-engineer: {session.engineer_id} FAILED — {err}",
                        file=sys.stderr,
                    )

        # Best-effort heartbeat provisioning for started Claude sessions. The
        # heartbeat adapter sends Claude /loop commands; Codex/Gemini seats
        # are already fully started by the generic launcher path above.
        for session in started:
            if not self._session_supports_heartbeat_provisioning(session):
                continue
            try:
                _provisioned, detail = self.hooks.provision_session_heartbeat(session)
                if detail:
                    print(detail)
            except Exception as exc:  # noqa: BLE001 - heartbeat is non-fatal
                print(f"heartbeat ({session.engineer_id}): {exc}", file=sys.stderr)

        if failures:
            failed_ids = [eid for eid, _ in failures]
            raise self.hooks.error_cls(
                f"batch-start-engineer: {len(failures)}/{len(engineer_ids)} "
                f"seats failed to start: {failed_ids}. "
                "Not opening iTerm window; fix the failing seats then re-run."
            )

        # Phase 2 — single atomic open-monitor.
        if skip_iterm:
            print("batch-start-engineer: --no-iterm set, skipping Phase 2")
            return 0

        project = self.hooks.load_project_or_current(project_name)
        if not project.monitor_engineers:
            print(
                f"batch-start-engineer: project '{project.name}' has no "
                "monitor_engineers; skipping iTerm window. Started tmux "
                "sessions remain alive — attach manually if needed.",
                file=sys.stderr,
            )
            return 0
        if project.window_mode != "tabs-1up":
            # For non-tabs modes (e.g. project-monitor) we defer to the same
            # path window_open_monitor uses, which may also start a monitor
            # session. Safe to share the code.
            self.hooks.session_service.start_project(
                project, ensure_monitor=True, reset=False
            )
        self.hooks.open_monitor_window(
            project,
            self.hooks.load_project_sessions(project.name),
            self.hooks.load_engineers(),
        )
        return 0

    def session_provision_heartbeat(self, args: Any) -> int:
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        if not self._session_supports_heartbeat_provisioning(session):
            tool = str(getattr(session, "tool", "") or "unknown")
            print(
                f"{session.engineer_id}: heartbeat skipped for {tool} session "
                "(Claude /loop provisioning only)"
            )
            return 0
        provisioned, detail = self.hooks.provision_session_heartbeat(
            session,
            force=bool(args.force),
            dry_run=bool(args.dry_run),
        )
        if detail:
            print(detail)
        already_verified = "already verified" in detail.lower() if detail else False
        return 0 if provisioned or args.dry_run or already_verified else 1

    def session_stop_engineer(self, args: Any) -> int:
        self._require_dispatch_authority("session stop-engineer")
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        self.hooks.session_service.stop_engineer(session, close_iterm_pane=not getattr(args, "keep_iterm_tab", False))
        return 0

    def _require_rename_hooks(self) -> None:
        missing = [
            name
            for name in (
                "write_project",
                "write_session",
                "session_path",
                "archive_if_exists",
                "identity_name",
                "runtime_dir_for_identity",
                "secret_file_for",
                "session_name_for",
                "workspaces_root",
                "ensure_dir",
                "ensure_secret_permissions",
            )
            if getattr(self.hooks, name) is None
        ]
        if missing:
            raise self.hooks.error_cls(
                f"session rename unavailable; missing hooks: {', '.join(missing)}"
            )

    def _kill_project_scoped_sessions(self, project_name: str, seat_id: str) -> list[str]:
        prefix = f"{project_name}-{seat_id}-"
        try:
            result = subprocess.run(
                ["tmux", "list-sessions", "-F", "#{session_name}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        killed: list[str] = []
        for session_name in [line.strip() for line in result.stdout.splitlines() if line.strip()]:
            if not session_name.startswith(prefix):
                continue
            subprocess.run(
                ["tmux", "kill-session", "-t", f"={session_name}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            killed.append(session_name)
        return killed

    def session_rename(self, args: Any) -> int:
        self._require_rename_hooks()
        from_seat = str(getattr(args, "from_seat", "") or "").strip()
        to_seat = str(getattr(args, "to_seat", "") or "").strip()
        if not from_seat or not to_seat:
            raise self.hooks.error_cls("session rename requires --from and --to")
        if from_seat == to_seat:
            print(f"{from_seat} unchanged")
            return 0

        project = self.hooks.load_project_or_current(getattr(args, "project", None))
        project_sessions = self.hooks.load_project_sessions(project.name)
        if from_seat not in project_sessions:
            raise self.hooks.error_cls(f"{project.name}:{from_seat} session not found")
        if to_seat in project_sessions:
            raise self.hooks.error_cls(f"{project.name}:{to_seat} session already exists")
        old_session = project_sessions[from_seat]

        self._kill_project_scoped_sessions(project.name, from_seat)
        try:
            self.hooks.session_service.stop_engineer(old_session, close_iterm_pane=True)
        except Exception as exc:
            print(f"session rename: stop skipped for {old_session.session}: {exc}", file=sys.stderr)

        new_identity = self.hooks.identity_name(
            old_session.tool,
            old_session.auth_mode,
            old_session.provider,
            to_seat,
            old_session.project,
        )
        new_session = type(old_session)(
            engineer_id=to_seat,
            project=old_session.project,
            tool=old_session.tool,
            auth_mode=old_session.auth_mode,
            provider=old_session.provider,
            identity=new_identity,
            workspace=str(self.hooks.workspaces_root / old_session.project / to_seat),
            runtime_dir=str(self.hooks.runtime_dir_for_identity(old_session.tool, old_session.auth_mode, new_identity)),
            session=self.hooks.session_name_for(old_session.project, to_seat, old_session.tool),
            bin_path=old_session.bin_path,
            monitor=old_session.monitor,
            legacy_sessions=[*list(old_session.legacy_sessions), old_session.session],
            launch_args=list(old_session.launch_args),
            secret_file="",
            wrapper=old_session.wrapper,
        )
        if old_session.secret_file:
            new_session.secret_file = str(
                self.hooks.secret_file_for(old_session.tool, old_session.provider, to_seat)
            )

        for old_path_raw, new_path_raw in (
            (old_session.workspace, new_session.workspace),
            (old_session.runtime_dir, new_session.runtime_dir),
            (old_session.secret_file, new_session.secret_file),
        ):
            if not old_path_raw or not new_path_raw:
                continue
            old_path = Path(old_path_raw)
            new_path = Path(new_path_raw)
            if not old_path.exists():
                continue
            self.hooks.ensure_dir(new_path.parent)
            if new_path.exists():
                raise self.hooks.error_cls(f"session rename target already exists: {new_path}")
            shutil.move(str(old_path), str(new_path))
            if new_path == Path(new_session.secret_file):
                self.hooks.ensure_secret_permissions(new_path)

        self.hooks.write_session(new_session)
        self.hooks.archive_if_exists(self.hooks.session_path(project.name, from_seat).parent, "sessions")
        project.engineers = [to_seat if item == from_seat else item for item in project.engineers]
        project.monitor_engineers = [
            to_seat if item == from_seat else item for item in project.monitor_engineers
        ]
        if project.seat_overrides and from_seat in project.seat_overrides and to_seat not in project.seat_overrides:
            project.seat_overrides[to_seat] = project.seat_overrides.pop(from_seat)
        self.hooks.write_project(project)
        self.hooks.session_service.start_engineer(new_session, reset=False)
        print(new_session.session)
        return 0

    def session_start_project(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(args.project)
        started_ids = self.hooks.session_service.project_autostart_engineer_ids(
            project,
            ensure_monitor=not args.no_monitor,
        )
        self.hooks.session_service.start_project(project, ensure_monitor=not args.no_monitor, reset=args.reset)
        print(",".join(started_ids))
        return 0

    def session_status(self, args: Any) -> int:
        if args.project:
            project = self.hooks.load_project_or_current(args.project)
            project_sessions = self.hooks.load_project_sessions(project.name)
            print(project.monitor_session, "running" if self.hooks.tmux_has_session(project.monitor_session) else "stopped")
            for engineer_id in project.engineers:
                if engineer_id in project_sessions:
                    session = project_sessions[engineer_id]
                    print(session.session, self.hooks.session_service.status(session))
            return 0
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        print(session.session, self.hooks.session_service.status(session))
        return 0

    def window_open_monitor(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(args.project)
        if not project.monitor_engineers:
            raise self.hooks.error_cls(f"{project.name} has no monitor engineers configured")
        if project.window_mode != "tabs-1up":
            self.hooks.session_service.start_project(project, ensure_monitor=True, reset=False)
        self.hooks.open_monitor_window(project, self.hooks.load_project_sessions(project.name), self.hooks.load_engineers())
        return 0

    def window_open_dashboard(self, args: Any) -> int:
        projects = self.hooks.load_projects()
        current_name = self.hooks.get_current_project_name(projects)
        ordered: list[Any] = []
        if current_name and current_name in projects:
            ordered.append(projects[current_name])
        for name in sorted(projects):
            if current_name and name == current_name:
                continue
            ordered.append(projects[name])
        visible_projects = [project for project in ordered if project.monitor_engineers]
        if not visible_projects:
            raise self.hooks.error_cls("No projects with monitor engineers configured")

        tabs_projects = [project.name for project in visible_projects if project.window_mode == "tabs-1up"]
        if tabs_projects:
            tabs_list = ", ".join(tabs_projects)
            raise self.hooks.error_cls(
                "window open-dashboard does not support tabs-1up projects. "
                f"Use `agent-admin window open-monitor <project>` for: {tabs_list}"
            )

        for project in visible_projects:
            self.hooks.session_service.start_project(project, ensure_monitor=True, reset=False)
        self.hooks.open_dashboard_window(visible_projects)
        return 0

    def window_open_grid(self, args: Any) -> int:
        projects = self.hooks.load_projects()
        project = projects.get(args.project)
        if project is None:
            raise self.hooks.error_cls(f"project not registered: {args.project}")
        result = window_ops.open_grid_window(
            project,
            recover=bool(getattr(args, "recover", False)),
            rebuild=bool(getattr(args, "rebuild", False)),
            open_memory=bool(getattr(args, "open_memory", False)),
            refresh_memories=bool(getattr(args, "refresh_memories", False)),
        )
        if not bool(getattr(args, "quiet", False)):
            line = str(result.get("summary", "")).strip()
            if not line:
                primary_seat = window_ops._project_primary_seat_id(project)
                worker_count = len(window_ops._project_grid_seat_ids(project))
                seat_count = worker_count if primary_seat == "memory" else worker_count + 1
                if seat_count <= 0:
                    seat_count = 1
                line = f"window open-grid: rebuilt project={project.name} seats={seat_count}"
                memories = result.get("memories")
                if isinstance(memories, dict) and "status" in memories:
                    line += f" memories={'touched' if memories.get('status') == 'ok' else 'skipped'}"
            print(line)
        return 0

    def window_open_engineer(self, args: Any) -> int:
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        project = self.hooks.load_project_or_current(session.project)
        if not self.hooks.tmux_has_session(session.session):
            if self.hooks.session_service.seat_requires_launch_confirmation(project, session.engineer_id):
                raise self.hooks.error_cls(
                    f"{project.name}:{session.engineer_id} requires explicit launch confirmation before start. "
                    "Use gstack-harness/scripts/start_seat.py to review the launch summary first, then rerun with --confirm-start."
                )
            self.hooks.session_service.start_engineer(session)
        if project.window_mode == "tabs-1up":
            self.hooks.open_project_tabs_window(
                project,
                self.hooks.load_project_sessions(project.name),
                self.hooks.load_engineers(),
            )
        else:
            self.hooks.open_engineer_window(session, self.hooks.load_engineers().get(session.engineer_id))
        return 0

    def window_reseed_pane(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(getattr(args, "project", None))
        result = window_ops.reseed_pane(project, args.seat)
        print(f"reseeded {result['project']}/{result['seat_id']}")
        return 0
