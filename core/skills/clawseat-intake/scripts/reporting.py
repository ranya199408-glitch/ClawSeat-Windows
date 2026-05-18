#!/usr/bin/env python3
"""Read-only reporting for socratic v2 decision logs."""

from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


def _registry_path() -> Path:
    return Path.home() / ".clawseat" / "projects.json"


def _decision_log_path(project: str) -> Path:
    return Path.home() / ".agents" / "memory" / "projects" / project / "decision"


def _parse_frontmatter_value(value: str) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        return json.loads(value)
    return value


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


def load_all_projects() -> list[str]:
    """Read active project names from ~/.clawseat/projects.json."""

    path = _registry_path()
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    projects = data.get("projects", data) if isinstance(data, dict) else data

    if isinstance(projects, dict):
        names: list[str] = []
        for name, entry in projects.items():
            if name == "schema_version":
                continue
            if isinstance(entry, dict) and entry.get("status") not in (None, "active"):
                continue
            names.append(str(name))
        return names

    if isinstance(projects, list):
        names = []
        for entry in projects:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict) and entry.get("name"):
                if entry.get("status") not in (None, "active"):
                    continue
                names.append(str(entry["name"]))
        return names

    return []


def load_decisions(project: str, *, since: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Read recent decision records for one project."""

    decision_dir = _decision_log_path(project)
    if not decision_dir.exists() or limit < 1:
        return []

    records: list[dict[str, Any]] = []
    for md_path in sorted(decision_dir.glob("*.md")):
        record = _parse_frontmatter(md_path)
        if not record:
            continue
        if since is not None and str(record.get("ts", "")) < since:
            continue
        records.append(record)
    records.sort(key=lambda record: str(record.get("ts", "")))
    return records[-limit:]


def aggregate(projects: list[str], *, since: str | None = None) -> list[dict[str, Any]]:
    """Merge project decision records and sort by timestamp ascending."""

    records: list[dict[str, Any]] = []
    for project in projects:
        records.extend(load_decisions(project, since=since))
    return sorted(records, key=lambda record: str(record.get("ts", "")))


def format_summary_card(aggregated: list[dict[str, Any]]) -> str:
    """Format a Chinese Markdown summary card grouped by project."""

    if not aggregated:
        return "## 决策汇总\n\n暂无决策记录。"

    grouped: "OrderedDict[str, list[dict[str, Any]]]" = OrderedDict()
    for record in aggregated:
        project = str(record.get("project") or "unknown")
        grouped.setdefault(project, []).append(record)

    sections: list[str] = []
    for project, records in grouped.items():
        sections.append(f"## {project} ({len(records)} 条)")
        for record in records:
            ts = str(record.get("ts", "unknown-ts"))
            seat = str(record.get("seat", "unknown"))
            title = str(record.get("title", "(untitled)"))
            sections.append(f"- {ts} [{seat}] {title}")
        sections.append("")
    return "\n".join(sections).rstrip()


def _print(records: list[dict[str, Any]], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(records, ensure_ascii=False, sort_keys=True))
    else:
        print(format_summary_card(records))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Write JSON instead of Markdown")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="All active projects, last 5 decisions each")
    summary.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    project = subparsers.add_parser("project", help="One project, full detail")
    project.add_argument("name")
    project.add_argument("--limit", type=int, default=20)
    project.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    all_projects = subparsers.add_parser("all", help="Cross-project aggregated decisions")
    all_projects.add_argument("--since", default=None)
    all_projects.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "summary":
        records: list[dict[str, Any]] = []
        for project in load_all_projects():
            records.extend(load_decisions(project, limit=5))
        records.sort(key=lambda record: str(record.get("ts", "")))
        _print(records, json_output=args.json)
        return 0

    if args.command == "project":
        records = load_decisions(args.name, limit=args.limit)
        _print(records, json_output=args.json)
        return 0

    if args.command == "all":
        records = aggregate(load_all_projects(), since=args.since)
        _print(records, json_output=args.json)
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
