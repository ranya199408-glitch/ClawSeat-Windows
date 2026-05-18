#!/usr/bin/env python3
from __future__ import annotations
import tempfile

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from ._adapter_types import (
    AdapterResult,
    BriefAction,
    BriefState,
    PendingFrontstageItem,
    PendingProjectOperation,
    SessionStatus,
)
from ._adapter_exec import (
    load_toml_like,
    parse_brief,
    parse_pending_frontstage,
    render_pending_item,
    serialize_adapter_result,
    write_pending_frontstage,
)

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[3]


from core.lib.real_home import real_user_home
from core.lib.tmux import tmux_session_alive as _tmux_session_alive


def _get_migration_root() -> Path:
    """Compute MIGRATION_ROOT at call time, not import time."""
    refac_override = os.environ.get("CLAWSEAT_REFAC_ROOT", "").strip()
    if refac_override:
        return Path(refac_override) / "migration"
    # Canonical production path: ClawSeat/core/migration/
    clawseat_root = os.environ.get("CLAWSEAT_ROOT", "").strip()
    if clawseat_root:
        return Path(clawseat_root) / "core" / "migration"
    return real_user_home() / "coding" / "ClawSeat" / "core" / "migration"


def _default_python_bin() -> str:
    return shutil.which("python3.12") or shutil.which("python3.11") or sys.executable


class ClawseatAdapter:
    def __init__(self, *, repo_root: str | Path = REPO_ROOT, python_bin: str | None = None) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.python_bin = python_bin or _default_python_bin()
        self.engine_script = self.repo_root / "core" / "engine" / "instantiate_seat.py"
        self.transport_router = self.repo_root / "core" / "transport" / "transport_router.py"
        self.current_project: str | None = None
        self.frontstage_epoch = 0
        self._project_profiles: dict[str, Path] = {}
        self._pending_inbox: dict[str, list[PendingProjectOperation]] = {}

    def profile_path_for(self, project_name: str, profile_path: str | Path | None = None) -> Path:
        if profile_path is not None:
            candidate = Path(profile_path).expanduser()
        else:
            from core.resolve import dynamic_profile_path
            dynamic = dynamic_profile_path(project_name)
            if dynamic.exists():
                candidate = dynamic
            else:
                legacy = Path(f"/tmp/{project_name}-profile.toml")
                if legacy.exists():
                    candidate = legacy
                else:
                    raise FileNotFoundError(f"no profile found for project {project_name}")
        declared_project = self._profile_project_name(candidate)
        if declared_project != project_name:
            raise ValueError(
                f"profile {candidate} declares project_name={declared_project!r}, expected {project_name!r}"
            )
        self._project_profiles[project_name] = candidate
        return candidate

    def switch_project(
        self,
        *,
        project_name: str,
        profile_path: str | Path | None = None,
    ) -> dict[str, Any]:
        previous_project = self.current_project
        drained: list[AdapterResult] = []
        if previous_project:
            drained = self.drain_pending_ops(project_name=previous_project)
        self.frontstage_epoch += 1
        resolved_profile = self.profile_path_for(project_name, profile_path)
        self.current_project = project_name
        brief = self.read_brief(project_name=project_name, profile_path=resolved_profile)
        return {
            "previous_project": previous_project,
            "current_project": self.current_project,
            "frontstage_epoch": self.frontstage_epoch,
            "profile_path": str(resolved_profile),
            "drained_operations": [serialize_adapter_result(item) for item in drained],
            "pending_inbox_depth": len(self._pending_inbox.get(project_name, [])),
            "brief": asdict(brief),
        }

    def pending_inbox(self, *, project_name: str | None = None) -> list[PendingProjectOperation]:
        selected = project_name or self.current_project
        if not selected:
            return []
        return list(self._pending_inbox.get(selected, []))

    def drain_pending_ops(self, *, project_name: str | None = None) -> list[AdapterResult]:
        """Execute all pending operations and return results.

        Operations are removed from the queue only after successful execution.
        If an operation fails, the failed op and remaining ops stay in the queue
        for retry.
        """
        selected = project_name or self.current_project
        if not selected:
            return []
        if self.current_project and selected != self.current_project:
            raise RuntimeError("may only drain the current_project inbox")
        queue = self._pending_inbox.get(selected, [])
        results: list[AdapterResult] = []
        while queue:
            operation = queue[0]
            try:
                if operation.kind == "dispatch":
                    result = self._execute_dispatch(
                        project_name=operation.project_name,
                        profile_path=operation.profile_path,
                        **operation.payload,
                    )
                elif operation.kind == "notify":
                    result = self._execute_notify(
                        project_name=operation.project_name,
                        profile_path=operation.profile_path,
                        **operation.payload,
                    )
                elif operation.kind == "complete":
                    result = self._execute_complete(
                        project_name=operation.project_name,
                        profile_path=operation.profile_path,
                        **operation.payload,
                    )
                else:
                    result = AdapterResult(
                        command=[], returncode=1,
                        stdout="", stderr=f"unknown operation kind: {operation.kind}",
                    )
            except (KeyError, AttributeError, TypeError) as exc:
                # Malformed queue entry — record the concrete exception
                # (with a short traceback) so the failure doesn't vanish
                # into a generic "failed" string. Audit M14. Stop
                # draining so the remaining ops stay in the queue for
                # retry after the bug is fixed.
                import traceback as _tb
                tb_snippet = "".join(_tb.format_exception_only(type(exc), exc)).strip()
                results.append(AdapterResult(
                    command=[], returncode=1,
                    stdout="",
                    stderr=f"{operation.kind} failed (malformed payload): {tb_snippet}",
                ))
                break
            except OSError as exc:
                # Subprocess / IO failure — keep it visible and stop draining.
                results.append(AdapterResult(
                    command=[], returncode=1,
                    stdout="", stderr=f"{operation.kind} failed (os error): {exc}",
                ))
                break
            results.append(result)
            if result.returncode != 0:
                break
            queue.pop(0)  # Remove only after successful execution
        return results

    def instantiate_seat(
        self,
        *,
        project_name: str,
        template_id: str,
        instance_id: str | None = None,
        repo_root: str | Path | None = None,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        command = [
            self.python_bin,
            str(self.engine_script),
            "--template-id",
            template_id,
            "--project-name",
            project_name,
            "--repo-root",
            str(Path(repo_root).expanduser() if repo_root else self.repo_root),
        ]
        if instance_id:
            command.extend(["--instance-id", instance_id])
        if force:
            command.append("--force")
        if dry_run:
            command.append("--dry-run")
        result = self._run_json(command)
        result["command"] = command
        return result

    def dispatch_task(
        self,
        *,
        project_name: str,
        source: str,
        target: str,
        task_id: str,
        title: str,
        objective: str,
        test_policy: str = "UPDATE",
        reply_to: str | None = None,
        profile_path: str | Path | None = None,
        notes: str | None = None,
        status_note: str | None = None,
        skip_notify: bool = False,
    ) -> AdapterResult:
        if not self._can_execute_for(project_name):
            return self._queue_operation(
                kind="dispatch",
                project_name=project_name,
                profile_path=profile_path,
                payload={
                    "source": source,
                    "target": target,
                    "task_id": task_id,
                    "title": title,
                    "objective": objective,
                    "test_policy": test_policy,
                    "reply_to": reply_to,
                    "notes": notes,
                    "status_note": status_note,
                    "skip_notify": skip_notify,
                },
            )
        return self._execute_dispatch(
            project_name=project_name,
            source=source,
            target=target,
            task_id=task_id,
            title=title,
            objective=objective,
            test_policy=test_policy,
            reply_to=reply_to,
            profile_path=profile_path,
            notes=notes,
            status_note=status_note,
            skip_notify=skip_notify,
        )

    def _execute_dispatch(
        self,
        *,
        project_name: str,
        source: str,
        target: str,
        task_id: str,
        title: str,
        objective: str,
        test_policy: str = "UPDATE",
        reply_to: str | None = None,
        profile_path: str | Path | None = None,
        notes: str | None = None,
        status_note: str | None = None,
        skip_notify: bool = False,
    ) -> AdapterResult:
        command = [
            self.python_bin,
            str(self.transport_router),
            "dispatch",
            "--profile",
            str(self.profile_path_for(project_name, profile_path)),
            "--source",
            source,
            "--target",
            target,
            "--task-id",
            task_id,
            "--title",
            title,
            "--objective",
            objective,
            "--test-policy",
            test_policy,
        ]
        if reply_to:
            command.extend(["--reply-to", reply_to])
        if notes:
            command.extend(["--notes", notes])
        if status_note:
            command.extend(["--status-note", status_note])
        if skip_notify:
            command.append("--skip-notify")
        return self._run(command)

    def notify_seat(
        self,
        *,
        project_name: str,
        source: str,
        target: str,
        message: str,
        task_id: str | None = None,
        reply_to: str | None = None,
        kind: str = "notice",
        profile_path: str | Path | None = None,
        skip_receipt: bool = False,
    ) -> AdapterResult:
        if not self._can_execute_for(project_name):
            return self._queue_operation(
                kind="notify",
                project_name=project_name,
                profile_path=profile_path,
                payload={
                    "source": source,
                    "target": target,
                    "message": message,
                    "task_id": task_id,
                    "reply_to": reply_to,
                    "kind": kind,
                    "skip_receipt": skip_receipt,
                },
            )
        return self._execute_notify(
            project_name=project_name,
            source=source,
            target=target,
            message=message,
            task_id=task_id,
            reply_to=reply_to,
            kind=kind,
            profile_path=profile_path,
            skip_receipt=skip_receipt,
        )

    def _execute_notify(
        self,
        *,
        project_name: str,
        source: str,
        target: str,
        message: str,
        task_id: str | None = None,
        reply_to: str | None = None,
        kind: str = "notice",
        profile_path: str | Path | None = None,
        skip_receipt: bool = False,
    ) -> AdapterResult:
        command = [
            self.python_bin,
            str(self.transport_router),
            "notify",
            "--profile",
            str(self.profile_path_for(project_name, profile_path)),
            "--source",
            source,
            "--target",
            target,
            "--message",
            message,
            "--kind",
            kind,
        ]
        if task_id:
            command.extend(["--task-id", task_id])
        if reply_to:
            command.extend(["--reply-to", reply_to])
        if skip_receipt:
            command.append("--skip-receipt")
        return self._run(command)

    def complete_handoff(
        self,
        *,
        project_name: str,
        source: str,
        task_id: str,
        target: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        verdict: str | None = None,
        frontstage_disposition: str | None = None,
        user_summary: str | None = None,
        next_action: str | None = None,
        profile_path: str | Path | None = None,
        ack_only: bool = False,
        skip_notify: bool = False,
    ) -> AdapterResult:
        if not self._can_execute_for(project_name):
            return self._queue_operation(
                kind="complete",
                project_name=project_name,
                profile_path=profile_path,
                payload={
                    "source": source,
                    "task_id": task_id,
                    "target": target,
                    "title": title,
                    "summary": summary,
                    "status": status,
                    "verdict": verdict,
                    "frontstage_disposition": frontstage_disposition,
                    "user_summary": user_summary,
                    "next_action": next_action,
                    "ack_only": ack_only,
                    "skip_notify": skip_notify,
                },
            )
        return self._execute_complete(
            project_name=project_name,
            source=source,
            task_id=task_id,
            target=target,
            title=title,
            summary=summary,
            status=status,
            verdict=verdict,
            frontstage_disposition=frontstage_disposition,
            user_summary=user_summary,
            next_action=next_action,
            profile_path=profile_path,
            ack_only=ack_only,
            skip_notify=skip_notify,
        )

    def _execute_complete(
        self,
        *,
        project_name: str,
        source: str,
        task_id: str,
        target: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        status: str = "completed",
        verdict: str | None = None,
        frontstage_disposition: str | None = None,
        user_summary: str | None = None,
        next_action: str | None = None,
        profile_path: str | Path | None = None,
        ack_only: bool = False,
        skip_notify: bool = False,
    ) -> AdapterResult:
        command = [
            self.python_bin,
            str(self.transport_router),
            "complete",
            "--profile",
            str(self.profile_path_for(project_name, profile_path)),
            "--source",
            source,
            "--task-id",
            task_id,
            "--status",
            status,
        ]
        if target:
            command.extend(["--target", target])
        if title:
            command.extend(["--title", title])
        if summary:
            command.extend(["--summary", summary])
        if verdict:
            command.extend(["--verdict", verdict])
        if frontstage_disposition:
            command.extend(["--frontstage-disposition", frontstage_disposition])
        if user_summary:
            command.extend(["--user-summary", user_summary])
        if next_action:
            command.extend(["--next-action", next_action])
        if ack_only:
            command.append("--ack-only")
        if skip_notify:
            command.append("--skip-notify")
        return self._run(command)

    def read_brief(self, *, project_name: str, profile_path: str | Path | None = None) -> BriefState:
        resolved_profile = self.profile_path_for(project_name, profile_path)
        snapshot = self._profile_snapshot(resolved_profile)
        brief_path = Path(snapshot.get("planner_brief_path", f"/tmp/{project_name}/.tasks/planner/PLANNER_BRIEF.md"))
        parsed = parse_brief(Path(brief_path))
        return BriefState(
            project_name=project_name,
            profile_path=snapshot.get("profile_path", str(resolved_profile)),
            brief_path=str(brief_path),
            title=parsed.get("title", ""),
            owner=parsed.get("owner", ""),
            status=parsed.get("status", ""),
            updated=parsed.get("updated", ""),
            frontstage_disposition=parsed.get("frontstage_disposition", ""),
            user_summary=parsed.get("user_summary", ""),
            action=BriefAction(
                requested_operation=parsed.get("requested_operation", ""),
                target_role=parsed.get("target_role", ""),
                target_instance=parsed.get("target_instance", ""),
                template_id=parsed.get("template_id", ""),
                reason=parsed.get("reason", ""),
                resume_task=parsed.get("resume_task", ""),
            ),
        )

    def check_session(self, *, project_name: str, seat_id: str) -> SessionStatus:
        session_path = Path(os.environ.get("SESSIONS_ROOT", str(real_user_home() / ".agents" / "sessions"))) / project_name / seat_id / "session.toml"
        if not session_path.exists():
            return SessionStatus(
                project_name=project_name,
                seat_id=seat_id,
                session_path=str(session_path),
                session_name="",
                exists=False,
                tmux_running=False,
                runtime_dir="",
                workspace="",
                tool="",
                provider="",
                auth_mode="",
            )
        session_data = load_toml_like(session_path)
        session_name = session_data.get("session", "")
        # Audit §10.5: exact-match via shared primitive; timeout=5 matches Audit M15.
        running = _tmux_session_alive(session_name, timeout=5.0) if session_name else False
        return SessionStatus(
            project_name=project_name,
            seat_id=seat_id,
            session_path=str(session_path),
            session_name=session_name,
            exists=True,
            tmux_running=running,
            runtime_dir=session_data.get("runtime_dir", ""),
            workspace=session_data.get("workspace", ""),
            tool=session_data.get("tool", ""),
            provider=session_data.get("provider", ""),
            auth_mode=session_data.get("auth_mode", ""),
        )

    def resolve_planner(self, *, project_name: str, profile_path: str | Path | None = None) -> dict[str, Any]:
        resolved_profile = self.profile_path_for(project_name, profile_path)
        snapshot = self._profile_snapshot(resolved_profile)
        planner = snapshot.get("planner_instance", "")
        if not planner:
            raise RuntimeError(f"unable to resolve planner for project {project_name}")
        session = self.check_session(project_name=project_name, seat_id=planner)
        return {
            "project_name": project_name,
            "profile_path": snapshot.get("profile_path", str(resolved_profile)),
            "planner_instance": planner,
            "active_loop_owner": snapshot.get("active_loop_owner", ""),
            "heartbeat_owner": snapshot.get("heartbeat_owner", ""),
            "seats": snapshot.get("seats", []),
            "session": asdict(session),
        }

    def read_pending_frontstage(
        self,
        *,
        project_name: str,
        profile_path: str | Path | None = None,
    ) -> list[PendingFrontstageItem]:
        path = self._pending_frontstage_path(project_name, profile_path)
        items = parse_pending_frontstage(path)
        return [item for item in items if not item.resolved]

    def resolve_frontstage_item(
        self,
        *,
        project_name: str,
        item_id: str,
        resolution: str,
        resolved_by: str,
        profile_path: str | Path | None = None,
    ) -> PendingFrontstageItem:
        if resolved_by not in {"koder", "user"}:
            raise ValueError("resolved_by must be 'koder' or 'user'")
        path = self._pending_frontstage_path(project_name, profile_path)
        items = parse_pending_frontstage(path)
        target: PendingFrontstageItem | None = None
        updated: list[PendingFrontstageItem] = []
        for item in items:
            if item.item_id == item_id:
                target = PendingFrontstageItem(
                    item_id=item.item_id,
                    item_type=item.item_type,
                    related_task=item.related_task,
                    summary=item.summary,
                    planner_recommendation=item.planner_recommendation,
                    koder_default_action=item.koder_default_action,
                    user_input_needed=item.user_input_needed,
                    blocking=item.blocking,
                    options=list(item.options),
                    resolved=True,
                    resolved_by=resolved_by,
                    resolved_at=self._utc_now_iso(),
                    resolution=resolution,
                    section="archived",
                )
                updated.append(target)
                continue
            updated.append(item)
        if target is None:
            raise FileNotFoundError(f"pending frontstage item not found: {item_id}")
        write_pending_frontstage(path, updated)
        return target

    def _run(self, command: list[str]) -> AdapterResult:
        result = subprocess.run(
            command,
            cwd=str(self.repo_root),
            text=True,
            capture_output=True,
            check=False,
        )
        return AdapterResult(
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _run_json(self, command: list[str]) -> dict[str, Any]:
        result = self._run(command)
        if not result.ok:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise RuntimeError(detail)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"expected JSON output from {' '.join(command)}: {exc}") from exc

    def _profile_snapshot(self, profile_path: Path) -> dict[str, Any]:
        # Write profile_path to a temp file to avoid shell injection via special
        # chars. The file must be removed in finally; previously it was left
        # behind with delete=False and accumulated under /tmp/ forever
        # (audit H9). Keep world-unreadable perms since the path may be
        # sensitive (user home, project dir).
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        try:
            tmp.write(str(profile_path))
            tmp.close()
            _tmp_path = tmp.name
            os.chmod(_tmp_path, 0o600)
            helper = (
                "import importlib.util, json, sys\n"
                "module_path = sys.argv[1]\n"
                "import pathlib\nprofile_path = pathlib.Path(sys.argv[2]).read_text().strip()\n"
                "spec = importlib.util.spec_from_file_location('clawseat_dynamic_common_helper', module_path)\n"
                "module = importlib.util.module_from_spec(spec)\n"
                "assert spec.loader is not None\n"
                "sys.modules[spec.name] = module\n"
                "spec.loader.exec_module(module)\n"
                "profile = module.load_profile(profile_path)\n"
                "preferred = getattr(module, 'preferred_planner_seat', None)\n"
                "planner = preferred(profile) if callable(preferred) else profile.active_loop_owner\n"
                "planner_brief = getattr(profile, 'planner_brief_path', profile.tasks_root / 'planner' / 'PLANNER_BRIEF.md')\n"
                "payload = {\n"
                "  'profile_path': str(profile.profile_path),\n"
                "  'project_name': profile.project_name,\n"
                "  'tasks_root': str(profile.tasks_root),\n"
                "  'planner_brief_path': str(planner_brief),\n"
                "  'active_loop_owner': profile.active_loop_owner,\n"
                "  'heartbeat_owner': profile.heartbeat_owner,\n"
                "  'planner_instance': planner,\n"
                "  'seats': list(profile.seats),\n"
                "}\n"
                "print(json.dumps(payload))\n"
            )
            result = self._run(
                [
                    self.python_bin,
                    "-c",
                    helper,
                    str(_get_migration_root() / "dynamic_common.py"),
                    _tmp_path,
                ]
            )
            if not result.ok:
                detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
                raise RuntimeError(f"failed to load profile snapshot for {profile_path}: {detail}")
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid profile snapshot output for {profile_path}: {exc}") from exc
        finally:
            try:
                os.unlink(tmp.name)
            except FileNotFoundError:
                pass

    def _profile_project_name(self, path: Path) -> str:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        return str(data.get("project_name", "")).strip()

    def _can_execute_for(self, project_name: str) -> bool:
        if self.current_project is None:
            self.current_project = project_name
            return True
        return project_name == self.current_project

    def _queue_operation(
        self,
        *,
        kind: str,
        project_name: str,
        profile_path: str | Path | None,
        payload: dict[str, Any],
    ) -> AdapterResult:
        resolved_profile = self.profile_path_for(project_name, profile_path)
        queued = PendingProjectOperation(
            kind=kind,
            project_name=project_name,
            frontstage_epoch=self.frontstage_epoch,
            profile_path=str(resolved_profile),
            payload=payload,
        )
        self._pending_inbox.setdefault(project_name, []).append(queued)
        current = self.current_project or "<unset>"
        return AdapterResult(
            command=[],
            returncode=0,
            stdout=f"queued {kind} for project {project_name} in pending inbox; current_project={current}; epoch={self.frontstage_epoch}",
            stderr="",
        )

    def _pending_frontstage_path(self, project_name: str, profile_path: str | Path | None = None) -> Path:
        resolved_profile = self.profile_path_for(project_name, profile_path)
        snapshot = self._profile_snapshot(resolved_profile)
        tasks_root = Path(snapshot.get("tasks_root", f"/tmp/{project_name}/.tasks"))
        return tasks_root / "planner" / "PENDING_FRONTSTAGE.md"

    def _utc_now_iso(self) -> str:
        result = self._run(
            [
                self.python_bin,
                "-c",
                "from datetime import datetime, timezone; print(datetime.now(timezone.utc).replace(microsecond=0).isoformat())",
            ]
        )
        if not result.ok:
            detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            raise RuntimeError(f"failed to generate UTC timestamp: {detail}")
        return result.stdout.strip()


__all__ = [
    "AdapterResult",
    "BriefAction",
    "BriefState",
    "ClawseatAdapter",
    "PendingFrontstageItem",
    "PendingProjectOperation",
    "SessionStatus",
]
