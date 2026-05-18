#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

from real_home import real_user_home  # noqa: E402
from state import Seat, get_seat, list_seats, open_db, upsert_seat  # noqa: E402
from utils import load_toml, now_iso  # noqa: E402


TOOL_NAMES = {"claude", "codex", "gemini", "minimax", "deepseek", "ark", "gpt-5"}


@dataclass(frozen=True)
class ParsedSession:
    project: str
    seat_id: str
    tool: str
    session_name: str


@dataclass
class KnownProject:
    name: str
    seats: set[str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reconcile live tmux sessions into ~/.agents/state.db seats.")
    parser.add_argument("--project", help="Limit reconcile to one project.")
    parser.add_argument("--tmux-output-file", help="Test hook: newline-separated tmux session names.")
    return parser.parse_args(argv)


def _real_home() -> Path:
    override = os.environ.get("CLAWSEAT_REAL_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return real_user_home()


def _project_root(home: Path) -> Path:
    return home / ".agents" / "projects"


def _session_root(home: Path) -> Path:
    return home / ".agents" / "sessions"


def _registry_path(home: Path) -> Path:
    override = os.environ.get("CLAWSEAT_REGISTRY_HOME", "").strip()
    if override:
        return Path(override).expanduser() / "projects.json"
    return home / ".clawseat" / "projects.json"


def _normalise_role(role: str, seat_id: str) -> str:
    role = role.strip()
    if role.startswith("minimal-"):
        print(
            f"warn: deprecated role namespace in session metadata mapped from {role} -> {role.removeprefix('minimal-')} "
            f"for seat={seat_id}",
            file=sys.stderr,
        )
        role = role.removeprefix("minimal-")
    if role.startswith("code-"):
        role = role.removeprefix("code-")
    role = {
        "planner-dispatcher": "planner",
        "project-memory": "memory",
        "memory-oracle": "memory",
        "frontstage-supervisor": "koder",
        "code-reviewer": "reviewer",
    }.get(role, role)
    candidate = role or seat_id
    for prefix, resolved in (
        ("builder", "builder"),
        ("planner", "planner"),
        ("reviewer", "reviewer"),
        ("designer", "designer"),
        ("patrol", "patrol"),
        ("memory", "memory"),
        ("koder", "koder"),
        ("engineer", "builder"),
    ):
        if candidate == prefix or candidate.startswith(prefix + "-"):
            return resolved
    return candidate or "specialist"


def _known_projects(home: Path) -> dict[str, KnownProject]:
    projects: dict[str, KnownProject] = {}
    root = _project_root(home)
    if root.is_dir():
        for project_toml in sorted(root.glob("*/project.toml")):
            try:
                data = load_toml(project_toml) or {}
            except Exception:
                continue
            name = str(data.get("name") or project_toml.parent.name).strip()
            seats = {str(item).strip() for item in data.get("engineers", []) if str(item).strip()}
            if name:
                projects[name] = KnownProject(name=name, seats=seats)
    registry = _registry_path(home)
    if registry.is_file():
        try:
            raw = json.loads(registry.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        for item in raw.get("projects", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            seats = set(projects.get(name, KnownProject(name, set())).seats)
            raw_seats = item.get("seats")
            if isinstance(raw_seats, dict):
                seats.update(str(seat).strip() for seat in raw_seats if str(seat).strip())
            primary = str(item.get("primary_seat") or "").strip()
            if primary:
                seats.add(primary)
            projects[name] = KnownProject(name=name, seats=seats)
    return projects


def parse_session_name(session_name: str, known_projects: dict[str, KnownProject]) -> ParsedSession | None:
    session_name = session_name.strip()
    if not session_name:
        return None
    for project_name in sorted(known_projects, key=len, reverse=True):
        prefix = project_name + "-"
        if not session_name.startswith(prefix):
            continue
        rest = session_name[len(prefix):]
        project = known_projects[project_name]
        for seat_id in sorted(project.seats, key=len, reverse=True):
            seat_prefix = seat_id + "-"
            if rest.startswith(seat_prefix):
                tool = rest[len(seat_prefix):]
                if tool:
                    return ParsedSession(project_name, seat_id, tool, session_name)
            if rest == seat_id:
                return ParsedSession(project_name, seat_id, "", session_name)
        parts = rest.rsplit("-", 1)
        if len(parts) == 2 and parts[1] in TOOL_NAMES:
            return ParsedSession(project_name, parts[0], parts[1], session_name)
    return None


def _tmux_sessions(*, output_file: str | None = None) -> set[str]:
    if output_file:
        return {line.strip() for line in Path(output_file).read_text(encoding="utf-8").splitlines() if line.strip()}
    try:
        result = subprocess.run(
            ["tmux", "ls", "-F", "#{session_name}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _session_record(home: Path, parsed: ParsedSession) -> dict:
    path = _session_root(home) / parsed.project / parsed.seat_id / "session.toml"
    if not path.is_file():
        return {}
    try:
        return load_toml(path) or {}
    except Exception:
        return {}


def _project_role(home: Path, parsed: ParsedSession) -> str:
    data = _session_record(home, parsed)
    role = str(data.get("role") or "").strip()
    if role:
        return _normalise_role(role, parsed.seat_id)
    project_path = _project_root(home) / parsed.project / "project.toml"
    if project_path.is_file():
        try:
            project = load_toml(project_path) or {}
            template_name = str(project.get("template_name") or "").strip()
            if template_name:
                template_path = _REPO_ROOT / "templates" / f"{template_name}.toml"
                if template_path.is_file():
                    template = load_toml(template_path) or {}
                    for engineer in template.get("engineers", []):
                        if str(engineer.get("id") or "").strip() == parsed.seat_id:
                            return _normalise_role(str(engineer.get("role") or ""), parsed.seat_id)
        except Exception as exc:
            print(f"warn: template role lookup failed for {parsed.session_name}: {exc}", file=sys.stderr)
    return _normalise_role("", parsed.seat_id)


def _seat_from_parsed(home: Path, parsed: ParsedSession, status: str, heartbeat: str | None) -> Seat:
    record = _session_record(home, parsed)
    return Seat(
        project=parsed.project,
        seat_id=parsed.seat_id,
        role=_project_role(home, parsed),
        tool=str(record.get("tool") or parsed.tool),
        auth_mode=str(record.get("auth_mode") or ""),
        provider=str(record.get("provider") or ""),
        status=status,
        last_heartbeat=heartbeat,
        session_name=str(record.get("session") or parsed.session_name),
        workspace=str(record.get("workspace") or "") or None,
    )


def _merge_seat(existing: Seat | None, update: Seat) -> Seat:
    if existing is None:
        return update
    return Seat(
        project=update.project,
        seat_id=update.seat_id,
        role=update.role or existing.role,
        tool=update.tool or existing.tool,
        auth_mode=update.auth_mode or existing.auth_mode,
        provider=update.provider or existing.provider,
        status=update.status,
        last_heartbeat=update.last_heartbeat,
        session_name=update.session_name or existing.session_name,
        workspace=update.workspace or existing.workspace,
    )


def _stale_warning(seat: Seat, now: datetime) -> str | None:
    if not seat.last_heartbeat:
        return None
    try:
        heartbeat = datetime.fromisoformat(seat.last_heartbeat.replace("Z", "+00:00"))
    except ValueError:
        return None
    if now - heartbeat > timedelta(minutes=5):
        return f"warn: stale heartbeat project={seat.project} seat={seat.seat_id} last_heartbeat={seat.last_heartbeat}"
    return None


def reconcile(*, project: str | None = None, tmux_output_file: str | None = None) -> dict[str, int]:
    home = _real_home()
    known = _known_projects(home)
    if project:
        known = {name: value for name, value in known.items() if name == project}
    tmux_names = _tmux_sessions(output_file=tmux_output_file)
    parsed_live = {
        (parsed.project, parsed.seat_id): parsed
        for session in tmux_names
        if (parsed := parse_session_name(session, known)) is not None
    }
    counts = {"live": 0, "dead": 0, "skipped": len(tmux_names) - len(parsed_live)}
    now = now_iso()
    now_dt = datetime.now(timezone.utc)
    with open_db() as conn:
        for key, parsed in sorted(parsed_live.items()):
            existing = get_seat(conn, parsed.project, parsed.seat_id)
            update = _seat_from_parsed(home, parsed, "live", now)
            upsert_seat(
                conn,
                _merge_seat(existing, update),
                allow_stopped_revival=True,
            )
            counts["live"] += 1
        for project_name in sorted(known):
            for seat in list_seats(conn, project_name, status="live"):
                if project and seat.project != project:
                    continue
                warning = _stale_warning(seat, now_dt)
                if warning:
                    print(warning, file=sys.stderr)
                if (seat.project, seat.seat_id) in parsed_live:
                    continue
                upsert_seat(
                    conn,
                    Seat(
                        project=seat.project,
                        seat_id=seat.seat_id,
                        role=seat.role,
                        tool=seat.tool,
                        auth_mode=seat.auth_mode,
                        provider=seat.provider,
                        status="dead",
                        last_heartbeat=seat.last_heartbeat,
                        session_name=seat.session_name,
                        workspace=seat.workspace,
                    ),
                )
                counts["dead"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    counts = reconcile(project=args.project, tmux_output_file=args.tmux_output_file)
    print(
        f"reconciled seats: live={counts['live']} dead={counts['dead']} skipped={counts['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
