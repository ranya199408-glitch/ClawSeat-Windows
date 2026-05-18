from __future__ import annotations

import argparse
import curses
import os
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TuiHooks:
    error_cls: type[Exception]
    load_projects: Callable[[], dict[str, Any]]
    load_engineers: Callable[[], dict[str, Any]]
    get_current_project_name: Callable[..., str | None]
    set_current_project: Callable[[str], None]
    load_project_sessions: Callable[[str], dict[str, Any]]
    display_name_for: Callable[[Any | None, str], str]
    engineer_summary: Callable[[Any, dict[tuple[str, str], Any] | None], str]
    session_summary: Callable[[Any], str]
    session_status: Callable[[Any], str]
    normalize_name: Callable[[str], str]
    cmd_project_create: Callable[[Any], int]
    cmd_project_layout_set: Callable[[Any], int]
    session_start_engineer: Callable[[Any], None]
    cmd_window_open_dashboard: Callable[[Any], int]
    open_engineer_window: Callable[[Any, Any | None], None]
    cmd_engineer_create: Callable[[Any], int]
    cmd_engineer_rename: Callable[[Any], int]
    cmd_engineer_rebind: Callable[[Any], int]
    cmd_engineer_secret_set: Callable[[Any], int]
    cmd_engineer_delete: Callable[[Any], int]


def prompt_input(stdscr: curses.window, prompt: str) -> str:
    curses.echo()
    height, width = stdscr.getmaxyx()
    stdscr.move(height - 2, 0)
    stdscr.clrtoeol()
    stdscr.addnstr(height - 2, 0, prompt, width - 1)
    stdscr.refresh()
    raw = stdscr.getstr(height - 1, 0).decode().strip()
    curses.noecho()
    stdscr.move(height - 1, 0)
    stdscr.clrtoeol()
    stdscr.move(height - 2, 0)
    stdscr.clrtoeol()
    return raw


def run_tui(stdscr: curses.window, hooks: TuiHooks) -> int:
    curses.curs_set(0)
    stdscr.keypad(True)
    selected = 0
    project_names = sorted(hooks.load_projects())
    current_project = hooks.get_current_project_name() or (project_names[0] if project_names else "")
    message = (
        "j/k: move  [/]: project  p: new project  l: layout  s: start  "
        "m: dashboard  o: open  c: create engineer  r: rename  b: rebind  "
        "e: edit secret  d: delete  q: quit"
    )

    def run_action(func: Callable[[], Any]) -> None:
        nonlocal message
        try:
            func()
            message = "ok"
        except hooks.error_cls as exc:
            message = f"error: {exc}"

    while True:
        projects = hooks.load_projects()
        engineers = hooks.load_engineers()
        project_names = sorted(projects)
        if not project_names:
            stdscr.erase()
            stdscr.addnstr(
                0,
                0,
                "No projects configured. Press p to create one, q to quit.",
                max(1, stdscr.getmaxyx()[1] - 1),
                curses.A_BOLD,
            )
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord("q"), 27):
                return 0
            if key == ord("p"):
                project_name = prompt_input(stdscr, "Project id: ")
                repo_root = prompt_input(stdscr, f"Repo root [{os.getcwd()}]: ")
                window_mode = prompt_input(stdscr, "Window mode (tabs-1up/tabs-2up): ") or "tabs-1up"
                if project_name:
                    run_action(
                        lambda: hooks.cmd_project_create(
                            argparse.Namespace(
                                project=project_name,
                                repo_root=repo_root,
                                window_mode=window_mode,
                                open_detail_windows=False,
                            )
                        )
                    )
                    current_project = hooks.normalize_name(project_name)
            continue

        if not current_project or current_project not in projects:
            current_project = hooks.get_current_project_name(projects) or project_names[0]
        project = projects[current_project]
        project_sessions = hooks.load_project_sessions(project.name)
        project_engineers = [engineers[item] for item in project.engineers if item in engineers]
        if project_engineers:
            selected = max(0, min(selected, len(project_engineers) - 1))
            current_engineer = project_engineers[selected]
            current_session = project_sessions.get(current_engineer.engineer_id)
        else:
            current_engineer = None
            current_session = None

        stdscr.erase()
        height, width = stdscr.getmaxyx()
        project_bar = "  ".join(f"[{name}]" if name == project.name else name for name in project_names)
        stdscr.addnstr(0, 0, f"Projects: {project_bar}", width - 1, curses.A_BOLD)
        stdscr.addnstr(
            1,
            0,
            (
                f"Monitor: {project.monitor_session}  Layout: {project.window_mode}  "
                f"DetailWindows: {project.open_detail_windows}"
            ),
            width - 1,
        )
        stdscr.addnstr(2, 0, message, width - 1)

        left_width = max(36, width // 3)
        for index, engineer in enumerate(project_engineers):
            prefix = "> " if index == selected else "  "
            session = project_sessions.get(engineer.engineer_id)
            tool = session.tool if session else engineer.default_tool
            auth_mode = session.auth_mode if session else engineer.default_auth_mode
            status = hooks.session_status(session) if session else "missing"
            name = hooks.display_name_for(engineer, engineer.engineer_id)
            line = f"{prefix}{name:<18} {tool:<6} {auth_mode:<5} {status}"
            attr = curses.A_REVERSE if index == selected else curses.A_NORMAL
            stdscr.addnstr(4 + index, 0, line, left_width - 1, attr)

        if current_engineer:
            detail = hooks.engineer_summary(current_engineer).splitlines()
            if current_session:
                detail.extend(["---", *hooks.session_summary(current_session).splitlines()])
            for index, line in enumerate(detail):
                if 4 + index >= height - 3:
                    break
                stdscr.addnstr(4 + index, left_width + 2, line, width - left_width - 3)

        stdscr.refresh()
        key = stdscr.getch()
        if key in (ord("q"), 27):
            return 0
        if key in (ord("["), curses.KEY_BTAB):
            if project_names:
                current_index = project_names.index(project.name)
                current_project = project_names[(current_index - 1) % len(project_names)]
                hooks.set_current_project(current_project)
                selected = 0
        elif key in (ord("]"), 9):
            if project_names:
                current_index = project_names.index(project.name)
                current_project = project_names[(current_index + 1) % len(project_names)]
                hooks.set_current_project(current_project)
                selected = 0
        if key in (ord("j"), curses.KEY_DOWN):
            selected = min(selected + 1, max(0, len(project_engineers) - 1))
        elif key in (ord("k"), curses.KEY_UP):
            selected = max(selected - 1, 0)
        elif key == ord("p"):
            project_name = prompt_input(stdscr, "Project id: ")
            repo_root = prompt_input(stdscr, f"Repo root [{os.getcwd()}]: ")
            window_mode = prompt_input(stdscr, "Window mode (tabs-1up/tabs-2up): ") or "tabs-1up"
            if project_name:
                run_action(
                    lambda: hooks.cmd_project_create(
                        argparse.Namespace(
                            project=project_name,
                            repo_root=repo_root,
                            window_mode=window_mode,
                            open_detail_windows=False,
                        )
                    )
                )
                current_project = hooks.normalize_name(project_name)
                selected = 0
        elif key == ord("l"):
            window_mode = prompt_input(stdscr, f"Window mode [{project.window_mode}]: ") or project.window_mode
            monitor_engineers = prompt_input(
                stdscr,
                f"Monitor engineers csv [{','.join(project.monitor_engineers)}]: ",
            )
            open_detail = prompt_input(
                stdscr,
                f"Open detail windows true/false [{'true' if project.open_detail_windows else 'false'}]: ",
            )
            run_action(
                lambda: hooks.cmd_project_layout_set(
                    argparse.Namespace(
                        project=project.name,
                        window_mode=window_mode,
                        monitor_max_panes=None,
                        monitor_engineers=monitor_engineers if monitor_engineers else None,
                        open_detail_windows=open_detail if open_detail else None,
                    )
                )
            )
        elif key == ord("s") and current_session:
            run_action(lambda: hooks.session_start_engineer(current_session))
        elif key == ord("m"):
            run_action(lambda: hooks.cmd_window_open_dashboard(argparse.Namespace()))
        elif key == ord("o") and current_session:
            run_action(
                lambda: (
                    hooks.session_start_engineer(current_session),
                    hooks.open_engineer_window(current_session, current_engineer),
                )
            )
        elif key == ord("c"):
            engineer_id = prompt_input(stdscr, "Engineer id: ")
            tool = prompt_input(stdscr, "Tool (codex/claude/gemini): ")
            mode = prompt_input(stdscr, "Mode (oauth/api): ")
            provider = prompt_input(stdscr, "Provider: ")
            if engineer_id and tool and mode and provider:
                run_action(
                    lambda: hooks.cmd_engineer_create(
                        argparse.Namespace(
                            engineer=engineer_id,
                            project=project.name,
                            tool=tool,
                            mode=mode,
                            provider=provider,
                            no_monitor=False,
                        )
                    )
                )
        elif key == ord("r") and current_engineer:
            new_id = prompt_input(stdscr, f"Rename {current_engineer.engineer_id} to: ")
            if new_id:
                run_action(
                    lambda: hooks.cmd_engineer_rename(
                        argparse.Namespace(old=current_engineer.engineer_id, new=new_id)
                    )
                )
        elif key == ord("b") and current_session:
            mode = prompt_input(stdscr, "New mode (oauth/api): ")
            provider = prompt_input(stdscr, "New provider: ")
            if mode and provider:
                run_action(
                    lambda: hooks.cmd_engineer_rebind(
                        argparse.Namespace(
                            engineer=current_session.engineer_id,
                            project=current_session.project,
                            mode=mode,
                            provider=provider,
                        )
                    )
                )
        elif key == ord("e") and current_session and current_session.auth_mode == "api":
            key_name = prompt_input(stdscr, "Secret key name: ")
            value = prompt_input(stdscr, "Secret value: ")
            if key_name:
                run_action(
                    lambda: hooks.cmd_engineer_secret_set(
                        argparse.Namespace(
                            engineer=current_session.engineer_id,
                            project=current_session.project,
                            key=key_name,
                            value=value,
                        )
                    )
                )
        elif key == ord("d") and current_engineer:
            confirm = prompt_input(stdscr, f"Delete {current_engineer.engineer_id}? type yes: ")
            if confirm == "yes":
                run_action(
                    lambda: hooks.cmd_engineer_delete(
                        argparse.Namespace(engineer=current_engineer.engineer_id, project=project.name)
                    )
                )


def run_tui_app(hooks: TuiHooks) -> int:
    return curses.wrapper(lambda stdscr: run_tui(stdscr, hooks))
