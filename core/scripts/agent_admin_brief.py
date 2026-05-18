#!/usr/bin/env python3
"""ClawSeat v3 brief subcommand.

Memory writes brief markdown + appends task_created event to per-team queue.
Planner reads queue via 7-step loop (see core/lib/queue_io.py).

Subcommands:
  queue    Write brief file + append task_created event
  list     Show pending tasks for a team
  claim    Planner claims a pending task
  show     Show current state of a task_id

Phase 1 minimal scope: standalone CLI. Phase 2 integrates into agent_admin.py
PARSER_HOOKS dispatch.

See spec §4.2 (brief schema) + §4.3 (queue events).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_LIB = _REPO_ROOT / "core" / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

from queue_io import (  # noqa: E402
    QueueError,
    append_event,
    query_pending,
    read_current_state,
)

try:
    import yaml  # type: ignore
except ImportError as _exc:  # pragma: no cover
    raise SystemExit("PyYAML required for agent_admin_brief")


class _QuotedStrDumper(yaml.SafeDumper):
    """SafeDumper that single-quotes all str scalars.

    Why: default safe_dump emits plain ISO datetime strings, which round-trip
    through safe_load become datetime objects. jsonschema then rejects them
    because schema declares string. Quoting forces unambiguous str on load.
    Fix #B (post-review retest).
    """


def _quoted_str_representer(dumper, data):  # type: ignore[no-untyped-def]
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")


_QuotedStrDumper.add_representer(str, _quoted_str_representer)

# Post-review fix #4: input validation to prevent path traversal.
# Patterns must mirror the schemas: project/team match project_toml_v3.schema
# (^[a-z0-9][a-z0-9-]*$) and task_id matches brief.schema (^[A-Za-z0-9][A-Za-z0-9_.-]*$).
_PROJECT_TEAM_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class InputValidationError(RuntimeError):
    pass


def _validate_identifier(value: str, kind: str) -> None:
    pattern = _TASK_ID_PATTERN if kind == "task_id" else _PROJECT_TEAM_PATTERN
    if not pattern.match(value or ""):
        raise InputValidationError(
            f"invalid {kind}: {value!r} (must match {pattern.pattern})"
        )
    if ".." in value or "/" in value or "\\" in value:
        raise InputValidationError(
            f"invalid {kind}: {value!r} contains path-traversal characters"
        )


def _validate_cli_inputs(project: str, team: str, task_id: str | None = None) -> None:
    _validate_identifier(project, "project")
    _validate_identifier(team, "team")
    if task_id is not None:
        _validate_identifier(task_id, "task_id")


def _validate_external_brief_content(
    brief_text: str, source_path: str, project: str, team: str, task_id: str
) -> None:
    """Validate caller-supplied brief content (--brief-content-file).

    Post-retest #2: parse frontmatter, verify schema + CLI match. Raise
    InputValidationError on any failure.
    """
    if not brief_text.startswith("---\n"):
        raise InputValidationError(
            f"{source_path}: brief content must start with '---' frontmatter"
        )
    end = brief_text.find("\n---\n", 4)
    if end == -1:
        end = brief_text.find("\n---", 4)
    if end == -1:
        raise InputValidationError(f"{source_path}: unterminated frontmatter")

    try:
        data = yaml.safe_load(brief_text[4:end])
    except Exception as exc:  # noqa: BLE001
        raise InputValidationError(f"{source_path}: frontmatter parse error: {exc}")
    if not isinstance(data, dict):
        raise InputValidationError(f"{source_path}: frontmatter must be a mapping")

    # CLI match
    for field_name, expected in (("task_id", task_id), ("project", project), ("team", team)):
        actual = data.get(field_name)
        if actual is None:
            raise InputValidationError(
                f"{source_path}: brief missing required field {field_name!r}"
            )
        if str(actual) != str(expected):
            raise InputValidationError(
                f"{source_path}: brief.{field_name}={actual!r} mismatches CLI {field_name}={expected!r}"
            )

    # Schema minItems sanity (cheap fallback even without jsonschema)
    seats = data.get("seats_required")
    if not isinstance(seats, list) or not seats:
        raise InputValidationError(
            f"{source_path}: brief.seats_required must have minItems 1"
        )
    ac = data.get("acceptance_criteria") or {}
    mech = ac.get("mechanical")
    if not isinstance(mech, list) or not mech:
        raise InputValidationError(
            f"{source_path}: brief.acceptance_criteria.mechanical must have minItems 1"
        )


def _agents_root() -> Path:
    return Path(
        os.environ.get(
            "CLAWSEAT_REAL_HOME",
            os.environ.get("HOME", str(Path.home())),
        )
    ).expanduser() / ".agents"


def _project_team_root(project: str, team: str) -> Path:
    return _agents_root() / "tasks" / project / team


def _queue_path(project: str, team: str) -> Path:
    return _project_team_root(project, team) / "tasks.queue.jsonl"


def _list_teams(project: str) -> list[str]:
    """Return all team subdirs under tasks/<project>/ that have a queue file."""
    proj_root = _agents_root() / "tasks" / project
    if not proj_root.exists():
        return []
    teams = []
    for child in proj_root.iterdir():
        if not child.is_dir():
            continue
        if (child / "tasks.queue.jsonl").exists() or (child / "brief").exists():
            teams.append(child.name)
    return sorted(teams)


def _resolve_cross_team_upstream(
    project: str, current_team: str, task_id: str
) -> tuple[str, str] | None:
    """Post-retest #5: locate a task_id across ALL teams in the project.

    Returns (team, status) if found, None otherwise. Used to evaluate
    cross-team depends_on without forcing planner to know which team owns
    each upstream task.
    """
    teams = _list_teams(project)
    for team in teams:
        if team == current_team:
            continue
        q = _queue_path(project, team)
        if not q.exists():
            continue
        state = read_current_state(q)
        if task_id in state:
            return team, state[task_id].status
    return None


def _brief_path(project: str, team: str, task_id: str) -> Path:
    return _project_team_root(project, team) / "brief" / f"{task_id}.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def cmd_queue(args: argparse.Namespace) -> int:
    """Append task_created event + write brief markdown skeleton.

    Post-review fixes:
    - #4 input validation (project/team/task_id pattern + path-traversal block)
    - #5 atomic non-destructive write (temp file → rename only after append)
    - #7 schema-valid skeleton (seats_required + mechanical have ≥1 item)
    """
    try:
        _validate_cli_inputs(args.project, args.team, args.task_id)
    except InputValidationError as exc:
        print(f"input validation failed: {exc}", file=sys.stderr)
        return 2

    project = args.project
    team = args.team
    task_id = args.task_id

    brief = _brief_path(project, team, task_id)
    brief.parent.mkdir(parents=True, exist_ok=True)

    # Pre-check overwrite policy BEFORE writing anything (Fix #5)
    brief_pre_exists = brief.exists()
    if brief_pre_exists and not args.force:
        print(f"refusing to overwrite existing brief: {brief}", file=sys.stderr)
        return 2

    if args.brief_content_file:
        brief_text = Path(args.brief_content_file).read_text(encoding="utf-8")
        # Post-retest #2: when caller supplies content, still validate it
        # both against brief schema (minItems etc.) AND against CLI args
        # (no mismatched task_id/project/team).
        try:
            _validate_external_brief_content(
                brief_text, args.brief_content_file, project, team, task_id
            )
        except InputValidationError as exc:
            print(f"brief content validation failed: {exc}", file=sys.stderr)
            return 2
    else:
        # Fix #B (post-review retest): build dict + yaml.safe_dump to handle
        # quotes / special chars / non-string scalars correctly. Also forces
        # created to be a string (default yaml.safe_dump would emit ISO without
        # quotes which PyYAML on load parses as datetime).
        frontmatter = {
            "task_id": str(task_id),
            "project": str(project),
            "team": str(team),
            "created": _utc_now(),
            "created_by": "memory",
            "objective": str(args.objective),
            "depends_on": list(args.depends_on or []),
            "acceptance_criteria": {
                "mechanical": [
                    "TODO: replace with a real mechanical command before dispatch"
                ],
                "reviewer": [],
                "operator": [],
            },
            "seats_required": list(args.seats_required or ["builder"]),
            "fuzz_required": False,
            "priority": "P2",
            "notify_on_completion": ["memory"],
        }
        # default_style='"' would force JSON-quoting every string. We instead
        # use default mode but specify default_flow_style=False + allow_unicode
        # so strings with quotes/colons get properly escaped, and `created`
        # stays a quoted string (because we passed it as a Python str).
        # Explicit-quoting `created` removes ambiguity on round-trip parse.
        yaml_body = yaml.dump(
            frontmatter,
            Dumper=_QuotedStrDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=4096,
        )
        brief_text = (
            "---\n"
            + yaml_body
            + "---\n\n"
            "# Brief 正文\n\n"
            "## 目标\n\n"
            + str(args.objective).strip()
            + "\n\n"
            "## 验收说明\n\n"
            "<待 memory 补全 mechanical/reviewer/operator 路由项>\n"
        )

    # Fix #5: write to temp file, atomic rename ONLY after append succeeds.
    # If append fails, we unlink the temp file and leave any pre-existing brief alone.
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{task_id}.", suffix=".tmp", dir=str(brief.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(brief_text)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    queue = _queue_path(project, team)
    event = {
        "event_type": "task_created",
        "actor": "memory",
        "task_id": task_id,
        "brief_path": str(brief.relative_to(_agents_root())),
        "parent_task_id": args.parent_task_id,
        "depends_on": args.depends_on or [],
    }
    try:
        result = append_event(queue, event)
    except QueueError as exc:
        # Fix #5: never unlink pre-existing brief on append failure.
        tmp_path.unlink(missing_ok=True)
        print(f"queue append failed: {exc}", file=sys.stderr)
        return 1

    # Append succeeded; atomic rename temp → final.
    os.replace(tmp_path, brief)

    print(f"queued task {task_id}")
    print(f"  brief: {brief}")
    print(f"  queue: {queue}")
    print(f"  seq:   {result['seq']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Show pending tasks for a team. Default: pending only; --all shows all."""
    try:
        _validate_cli_inputs(args.project, args.team)
    except InputValidationError as exc:
        print(f"input validation failed: {exc}", file=sys.stderr)
        return 2
    queue = _queue_path(args.project, args.team)
    if not queue.exists():
        print(f"queue not initialized: {queue}", file=sys.stderr)
        return 0

    state = read_current_state(queue)
    if args.all:
        rows = list(state.values())
    else:
        rows = [ts for ts in state.values() if ts.status == "task_created"]
    rows.sort(key=lambda ts: ts.last_seq)

    if not rows:
        print(f"no {'tasks' if args.all else 'pending tasks'} in {args.project}/{args.team}")
        return 0

    for ts in rows:
        depends = ",".join(ts.depends_on) if ts.depends_on else "-"
        print(f"{ts.task_id}\t{ts.status}\t{ts.actor}\t{ts.last_event_ts}\tdepends_on={depends}")
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    """Planner claims a pending task. Appends task_claimed event.

    Checks depends_on first; if unmet, writes task_waiting_for instead.
    (Fix #6: task_created -> task_waiting_for transition allowed by queue_io
    VALID_TRANSITIONS as of v3 Phase 1 post-review.)
    """
    try:
        _validate_cli_inputs(args.project, args.team, args.task_id)
    except InputValidationError as exc:
        print(f"input validation failed: {exc}", file=sys.stderr)
        return 2
    queue = _queue_path(args.project, args.team)
    state = read_current_state(queue)
    ts = state.get(args.task_id)
    if ts is None:
        print(f"task_id {args.task_id!r} not in queue", file=sys.stderr)
        return 2
    # Fix #A (post-review retest): allow retry from task_waiting_for state.
    # State machine permits task_waiting_for → task_claimed when deps now met,
    # or task_waiting_for → task_waiting_for if still blocked.
    if ts.status not in ("task_created", "task_waiting_for"):
        print(
            f"task_id {args.task_id!r} is in state {ts.status!r}, not claimable",
            file=sys.stderr,
        )
        return 2

    # Post-retest #5: check depends_on across ALL teams in the project.
    # Local queue checked first; if absent, fall through to cross-team scan.
    unmet = []
    for upstream_id in ts.depends_on:
        up = state.get(upstream_id)
        if up is not None:
            if up.status != "task_done":
                unmet.append(upstream_id)
            continue
        cross = _resolve_cross_team_upstream(args.project, args.team, upstream_id)
        if cross is None or cross[1] != "task_done":
            unmet.append(upstream_id)

    if unmet:
        for up_id in unmet:
            event = {
                "event_type": "task_waiting_for",
                "actor": args.actor,
                "task_id": args.task_id,
                "waiting_for": up_id,
            }
            try:
                append_event(queue, event)
            except QueueError as exc:
                print(f"waiting_for append failed: {exc}", file=sys.stderr)
                return 1
        print(f"task {args.task_id} blocked on upstream: {unmet}")
        return 3

    event = {
        "event_type": "task_claimed",
        "actor": args.actor,
        "task_id": args.task_id,
    }
    try:
        result = append_event(queue, event)
    except QueueError as exc:
        print(f"claim append failed: {exc}", file=sys.stderr)
        return 1
    print(f"claimed {args.task_id} (seq {result['seq']})")
    print(f"  brief: {ts.brief_path}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    try:
        _validate_cli_inputs(args.project, args.team, args.task_id)
    except InputValidationError as exc:
        print(f"input validation failed: {exc}", file=sys.stderr)
        return 2
    queue = _queue_path(args.project, args.team)
    state = read_current_state(queue)
    ts = state.get(args.task_id)
    if ts is None:
        print(f"task_id {args.task_id!r} not in queue", file=sys.stderr)
        return 2
    print(json.dumps(
        {
            "task_id": ts.task_id,
            "status": ts.status,
            "last_seq": ts.last_seq,
            "last_event_ts": ts.last_event_ts,
            "actor": ts.actor,
            "brief_path": ts.brief_path,
            "depends_on": ts.depends_on,
            "waiting_for": ts.waiting_for,
            "verdict": ts.verdict,
            "fail_reason": ts.fail_reason,
            "bounce_reason": ts.bounce_reason,
            "reset_count": ts.reset_count,
        },
        indent=2,
    ))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent_admin_brief",
        description="ClawSeat v3 brief / queue subcommand (Phase 1 minimal).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("queue", help="Write brief + append task_created event")
    q.add_argument("--project", required=True)
    q.add_argument("--team", required=True)
    q.add_argument("--task-id", required=True, dest="task_id")
    q.add_argument("--objective", required=True)
    q.add_argument("--depends-on", nargs="*", default=[], dest="depends_on")
    q.add_argument(
        "--seats-required",
        nargs="*",
        default=None,
        dest="seats_required",
        help="Seats required (default: ['builder']). Schema requires non-empty.",
    )
    q.add_argument("--parent-task-id", default=None, dest="parent_task_id")
    q.add_argument("--brief-content-file", default=None, dest="brief_content_file",
                   help="Optional path to pre-written brief markdown (overrides skeleton).")
    q.add_argument("--force", action="store_true", help="Overwrite existing brief.")
    q.set_defaults(func=cmd_queue)

    l = sub.add_parser("list", help="List tasks for a team (default: pending only)")
    l.add_argument("--project", required=True)
    l.add_argument("--team", required=True)
    l.add_argument("--all", action="store_true")
    l.set_defaults(func=cmd_list)

    c = sub.add_parser("claim", help="Planner claims a pending task")
    c.add_argument("--project", required=True)
    c.add_argument("--team", required=True)
    c.add_argument("--task-id", required=True, dest="task_id")
    c.add_argument("--actor", required=True,
                   help="Format: <role>@<tool>, e.g. planner@claude")
    c.set_defaults(func=cmd_claim)

    s = sub.add_parser("show", help="Show current state of a task_id")
    s.add_argument("--project", required=True)
    s.add_argument("--team", required=True)
    s.add_argument("--task-id", required=True, dest="task_id")
    s.set_defaults(func=cmd_show)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
