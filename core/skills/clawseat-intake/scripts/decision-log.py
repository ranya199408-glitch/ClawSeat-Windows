#!/usr/bin/env python3
"""Append and read socratic v2 project decision logs."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _agents_home() -> Path:
    return Path.home() / ".agents"


def _registry_path() -> Path:
    return Path.home() / ".clawseat" / "projects.json"


def _memory_home() -> Path:
    return _agents_home() / "memory"


def _decision_dir(project: str) -> Path:
    return _memory_home() / "projects" / project / "decision"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slug(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_title.lower()).strip("-")
    if not slug:
        slug = "decision"
    return slug[:64].strip("-") or "decision"


def _safe_ts(ts: str) -> str:
    return ts.replace(":", "-").replace("/", "-")


def _decision_record_path(project: str, ts: str, title: str) -> Path:
    return _decision_dir(project) / f"{_safe_ts(ts)}-{_slug(title)}.md"


def _format_frontmatter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    text = str(value)
    if not text or any(char in text for char in ('"', ":", "#", "\n")) or text.strip() != text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _parse_frontmatter_value(value: str) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    return value


def _render_md(record: dict[str, Any]) -> str:
    frontmatter = {key: value for key, value in record.items() if key != "body"}
    lines = ["---"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {_format_frontmatter_value(value)}")
    lines.extend(["---", "", str(record.get("body", record.get("detail", "")))])
    return "\n".join(lines).rstrip() + "\n"


def _parse_frontmatter(md_path: Path) -> dict[str, Any]:
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}

    parsed: dict[str, Any] = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = _parse_frontmatter_value(value)
    return parsed


def append_decision(
    project: str,
    task_id: str,
    title: str,
    detail: str,
    seat: str = "planner",
    decision_type: str | None = None,
    *,
    auto_mode: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    """Append one decision record and return the stored payload."""

    if not project:
        raise ValueError("project is required")
    if not task_id:
        raise ValueError("task_id is required")
    if not title:
        raise ValueError("title is required")
    if not detail:
        raise ValueError("detail is required")

    record: dict[str, Any] = {
        "issue_id": str(uuid.uuid4()),
        "ts": _utc_now(),
        "task_id": task_id,
        "project": project,
        "seat": seat,
        "kind": "decision",
        "title": title,
        "status": "open",
        "detail": detail,
        "decision_type": decision_type or "auto",
        "auto_mode": auto_mode,
        "reason": reason or detail,
        "body": detail,
    }

    record_path = _decision_record_path(project, str(record["ts"]), title)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(_render_md(record), encoding="utf-8")
    return record


def list_decisions(project: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Return the last ``limit`` decision records for ``project`` by timestamp."""

    if limit < 1:
        return []

    decision_dir = _decision_dir(project)
    if not decision_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for md_path in sorted(decision_dir.glob("*.md")):
        record = _parse_frontmatter(md_path)
        if record:
            records.append(record)
    records.sort(key=lambda record: str(record.get("ts", "")))
    return records[-limit:]


def get_project_list() -> list[str]:
    """Read project names from ``~/.clawseat/projects.json`` without registry imports."""

    path = _registry_path()
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    projects = data.get("projects", data) if isinstance(data, dict) else data

    if isinstance(projects, dict):
        return [str(name) for name in projects.keys()]
    if isinstance(projects, list):
        names: list[str] = []
        for entry in projects:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict) and entry.get("name"):
                names.append(str(entry["name"]))
        return names
    return []


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    append = subparsers.add_parser("append", help="Append one decision")
    append.add_argument("project")
    append.add_argument("task_id")
    append.add_argument("title")
    append.add_argument("detail")
    append.add_argument("--seat", default="planner")
    append.add_argument("--decision-type", default=None)
    append.add_argument("--reason", default=None)
    append.add_argument("--manual", action="store_true", help="Mark auto_mode=false")

    list_parser = subparsers.add_parser("list", help="List recent decisions")
    list_parser.add_argument("project")
    list_parser.add_argument("--limit", type=int, default=50)

    subparsers.add_parser("projects", help="List registered projects")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "append":
        record = append_decision(
            args.project,
            args.task_id,
            args.title,
            args.detail,
            seat=args.seat,
            decision_type=args.decision_type,
            auto_mode=not args.manual,
            reason=args.reason,
        )
        print(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "list":
        print(json.dumps(list_decisions(args.project, limit=args.limit), ensure_ascii=False))
        return 0
    if args.command == "projects":
        print(json.dumps(get_project_list(), ensure_ascii=False))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
