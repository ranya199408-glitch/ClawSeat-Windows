from __future__ import annotations

import argparse
import os
import shlex
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class InfoHooks:
    error_cls: type[Exception]
    load_projects: Callable[[], dict[str, Any]]
    load_project_or_current: Callable[[str | None], Any]
    load_project: Callable[[str], Any]
    load_engineers: Callable[[], dict[str, Any]]
    load_sessions: Callable[[], dict[tuple[str, str], Any]]
    project_template_context: Callable[[Any], tuple[dict[str, Any], list[str], list[dict[str, object]]] | None]
    resolve_engineer: Callable[[str, dict[str, Any] | None], Any]
    resolve_engineer_session: Callable[..., Any]
    resolve_session: Callable[..., str]
    display_label: Callable[[Any | None, str], str]
    session_status: Callable[[Any], str]
    build_runtime: Callable[[Any], tuple[str, dict[str, str]]]
    default_launch_args: Callable[[Any], list[str]]


class InfoHandlers:
    def __init__(self, hooks: InfoHooks) -> None:
        self.hooks = hooks

    def resolved_launch_args(self, session: Any, cmd: list[str] | None = None) -> tuple[list[str], str]:
        if cmd:
            return list(cmd), "explicit_cmd"
        if session.launch_args:
            return list(session.launch_args), "session.launch_args"
        return list(self.hooks.default_launch_args(session)), "default_tool_args"

    def effective_launch_snapshot(self, session: Any, cmd: list[str] | None = None) -> dict[str, object]:
        resolved_args, source = self.resolved_launch_args(session, cmd=cmd)
        command = [session.bin_path, *resolved_args]
        return {
            "engineer_id": session.engineer_id,
            "project": session.project,
            "tool": session.tool,
            "auth_mode": session.auth_mode,
            "provider": session.provider,
            "workspace": session.workspace,
            "runtime_dir": session.runtime_dir,
            "binary": session.bin_path,
            "session_launch_args": list(session.launch_args),
            "default_launch_args": list(self.hooks.default_launch_args(session)),
            "effective_launch_args": resolved_args,
            "launch_args_source": source,
            "effective_command": " ".join(shlex.quote(part) for part in command),
        }

    def engineer_summary(self, engineer: Any, sessions: dict[tuple[str, str], Any] | None = None) -> str:
        session_map = sessions or self.hooks.load_sessions()
        engineer_sessions = [session for session in session_map.values() if session.engineer_id == engineer.engineer_id]
        return "\n".join(
            [
                f"id = {engineer.engineer_id}",
                f"display_name = {engineer.display_name}",
                f"label = {self.hooks.display_label(engineer, engineer.engineer_id)}",
                f"role = {engineer.role or '-'}",
                f"skills = {', '.join(engineer.skills) or '-'}",
                f"default_tool = {engineer.default_tool or '-'}",
                f"default_auth_mode = {engineer.default_auth_mode or '-'}",
                f"default_provider = {engineer.default_provider or '-'}",
                f"aliases = {', '.join(engineer.aliases) or '-'}",
                f"sessions = {', '.join(f'{s.project}:{s.session}' for s in engineer_sessions) or '-'}",
            ]
        )

    def session_summary(self, session: Any) -> str:
        return "\n".join(
            [
                f"engineer_id = {session.engineer_id}",
                f"project = {session.project}",
                f"tool = {session.tool}",
                f"auth_mode = {session.auth_mode}",
                f"provider = {session.provider}",
                f"identity = {session.identity}",
                f"workspace = {session.workspace}",
                f"runtime_dir = {session.runtime_dir}",
                f"session = {session.session}",
                f"secret_file = {session.secret_file or '-'}",
                f"legacy_sessions = {', '.join(session.legacy_sessions) or '-'}",
                f"launch_args = {', '.join(session.launch_args) or '-'}",
                f"status = {self.hooks.session_status(session)}",
            ]
        )

    def list_projects(self, args: Any) -> int:
        for project in self.hooks.load_projects().values():
            print(project.name)
        return 0

    def list_engineers(self, args: Any) -> int:
        for engineer in self.hooks.load_engineers().values():
            if engineer.engineer_id == "ancestor":
                continue
            print(
                f"{self.hooks.display_label(engineer, engineer.engineer_id)}\t"
                f"{engineer.default_tool or '-'}\t{engineer.default_auth_mode or '-'}\t"
                f"{engineer.default_provider or '-'}"
            )
        return 0

    def show_project(self, args: Any) -> int:
        project = self.hooks.load_project_or_current(args.project)
        print(f"name = {project.name}")
        print(f"repo_root = {project.repo_root}")
        print(f"monitor_session = {project.monitor_session}")
        print(f"window_mode = {project.window_mode}")
        print(f"monitor_max_panes = {project.monitor_max_panes}")
        print(f"open_detail_windows = {project.open_detail_windows}")
        print(f"engineers = {', '.join(project.engineers)}")
        print(f"monitor_engineers = {', '.join(project.monitor_engineers)}")
        return 0

    def show_engineer(self, args: Any) -> int:
        sessions = self.hooks.load_sessions()
        engineer = self.hooks.resolve_engineer(args.engineer)
        if args.project:
            project = self.hooks.load_project(args.project)
            derived_context = self.hooks.project_template_context(project)
            if derived_context:
                engineer = derived_context[0].get(engineer.engineer_id, engineer)
        print(self.engineer_summary(engineer, sessions))
        if args.project:
            print("---")
            print(
                self.session_summary(
                    self.hooks.resolve_engineer_session(
                        args.engineer,
                        project_name=args.project,
                        sessions=sessions,
                    )
                )
            )
        return 0

    def show(self, args: Any) -> int:
        return self.show_engineer(args)

    def resolve(self, args: Any) -> int:
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        if session.tool != args.tool:
            raise self.hooks.error_cls(f"{session.engineer_id} is bound to {session.tool}, not {args.tool}")
        print(session.identity)
        print(f"tool={session.tool}")
        print(f"mode={session.auth_mode}")
        print(f"provider={session.provider}")
        print(f"runtime_dir={session.runtime_dir}")
        if session.secret_file:
            print(f"secret_file={session.secret_file}")
        return 0

    def show_identity(self, args: Any) -> int:
        for session in self.hooks.load_sessions().values():
            if session.identity == args.identity:
                print(self.session_summary(session))
                return 0
        raise self.hooks.error_cls(f"Unknown identity: {args.identity}")

    def list_identities(self, args: Any) -> int:
        for session in self.hooks.load_sessions().values():
            print(
                f"{session.identity}\t{session.tool}\t{session.auth_mode}\t"
                f"{session.provider}\t{session.project}\t{session.engineer_id}"
            )
        return 0

    def run_engineer(self, args: Any) -> int:
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        binary, env = self.hooks.build_runtime(session)
        cmd = [binary]
        resolved_args, _ = self.resolved_launch_args(session, cmd=args.cmd)
        cmd.extend(resolved_args)
        os.execvpe(binary, cmd, env)
        return 0

    def session_effective_launch(self, args: Any) -> int:
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        snapshot = self.effective_launch_snapshot(session, cmd=getattr(args, "cmd", None))
        for key in (
            "engineer_id",
            "project",
            "tool",
            "auth_mode",
            "provider",
            "workspace",
            "runtime_dir",
            "binary",
        ):
            print(f"{key} = {snapshot[key]}")
        print(
            "session_launch_args = "
            + (", ".join(snapshot["session_launch_args"]) if snapshot["session_launch_args"] else "-")
        )
        print(
            "default_launch_args = "
            + (", ".join(snapshot["default_launch_args"]) if snapshot["default_launch_args"] else "-")
        )
        print(
            "effective_launch_args = "
            + (", ".join(snapshot["effective_launch_args"]) if snapshot["effective_launch_args"] else "-")
        )
        print(f"launch_args_source = {snapshot['launch_args_source']}")
        print(f"effective_command = {snapshot['effective_command']}")
        return 0

    def start(self, args: Any) -> int:
        session = self.hooks.resolve_engineer_session(args.engineer, project_name=getattr(args, "project", None))
        if session.tool != args.tool:
            raise self.hooks.error_cls(f"{session.engineer_id} is bound to {session.tool}, not {args.tool}")
        return self.run_engineer(argparse.Namespace(engineer=session.engineer_id, project=session.project, cmd=args.cmd))

    def start_identity(self, args: Any) -> int:
        for session in self.hooks.load_sessions().values():
            if session.identity == args.identity:
                return self.run_engineer(
                    argparse.Namespace(engineer=session.engineer_id, project=session.project, cmd=args.cmd)
                )
        raise self.hooks.error_cls(f"Unknown identity: {args.identity}")

    def session_name(self, args: Any) -> int:
        print(
            self.hooks.resolve_session(
                args.target,
                project_name=getattr(args, "project", None),
                prefer_current_project=False,
            )
        )
        return 0
