#!/usr/bin/env python3
"""Build and query derived indexes for Markdown memory KB records."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _memory_root() -> Path:
    agent_home = os.environ.get("AGENT_HOME")
    if agent_home:
        return Path(agent_home).expanduser().resolve() / ".agents" / "memory"
    return Path.home() / ".agents" / "memory"


def _projects_root() -> Path:
    return _memory_root() / "projects"


def _project_root(project: str) -> Path:
    return _projects_root() / project


def _index_dir(project: str) -> Path:
    return _project_root(project) / "_index"


def _registry_path() -> Path:
    return Path.home() / ".clawseat" / "projects.json"


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _write_timeline(path: Path, timeline: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in timeline),
        encoding="utf-8",
    )


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def parse_frontmatter(md_path: Path) -> dict[str, Any] | None:
    """Read YAML-style frontmatter from a Markdown file."""

    try:
        lines = md_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    if not lines or lines[0] != "---":
        return None

    parsed: dict[str, Any] = {}
    for line in lines[1:]:
        if line == "---":
            return parsed
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = _parse_value(value)
    return None


def _relative_record_path(project: str, path: Path) -> str:
    return path.relative_to(_project_root(project)).as_posix()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def build_files_index(project: str) -> dict[str, Any]:
    """Scan Markdown files for one project and extract frontmatter."""

    project_root = _project_root(project)
    files: list[dict[str, Any]] = []
    if project_root.exists():
        for md_path in sorted(project_root.rglob("*.md")):
            if "_index" in md_path.relative_to(project_root).parts:
                continue
            frontmatter = parse_frontmatter(md_path)
            if frontmatter is None:
                continue
            entry = dict(frontmatter)
            entry["path"] = _relative_record_path(project, md_path)
            entry["size"] = md_path.stat().st_size
            entry["mtime"] = _mtime_iso(md_path)
            files.append(entry)

    return {
        "version": 1,
        "last_built": _now_iso(),
        "project": project,
        "files": files,
    }


def _bigrams(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def build_search_index(files: dict[str, Any]) -> dict[str, Any]:
    """Build a small bigram inverted index from frontmatter text."""

    tokens: dict[str, list[str]] = {}
    for entry in files.get("files", []):
        path = str(entry.get("path", ""))
        text = " ".join(str(value) for value in entry.values() if isinstance(value, str))
        for token in _bigrams(text):
            tokens.setdefault(token, [])
            if path not in tokens[token]:
                tokens[token].append(path)
    return {
        "version": 1,
        "project": files.get("project"),
        "last_built": _now_iso(),
        "tokens": dict(sorted(tokens.items())),
    }


def build_links_index(files: dict[str, Any]) -> dict[str, Any]:
    """Extract wikilinks from indexed Markdown files."""

    project = str(files.get("project", ""))
    root = _project_root(project)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for entry in files.get("files", []):
        path = str(entry.get("path", ""))
        nodes.append({
            "id": path,
            "kind": entry.get("kind"),
            "label": entry.get("title", path),
        })
        try:
            text = (root / path).read_text(encoding="utf-8")
        except OSError:
            text = ""
        for target in re.findall(r"\[\[([^\]]+)\]\]", text):
            edges.append({"from": path, "to": target, "type": "references"})
    return {
        "version": 1,
        "project": project,
        "last_built": _now_iso(),
        "nodes": nodes,
        "edges": edges,
    }


def build_timeline(files: dict[str, Any]) -> list[dict[str, Any]]:
    """Return project events sorted by timestamp."""

    timeline = [
        {
            "ts": entry.get("ts", ""),
            "path": entry.get("path", ""),
            "kind": entry.get("kind", ""),
        }
        for entry in files.get("files", [])
    ]
    return sorted(timeline, key=lambda entry: str(entry.get("ts", "")))


def build_global_index(project_indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-project index summaries."""

    projects = []
    for project, index in sorted(project_indexes.items()):
        files = index.get("files", [])
        timeline = build_timeline(index)
        kinds = sorted({str(entry.get("kind")) for entry in files if entry.get("kind")})
        projects.append({
            "project": project,
            "file_count": len(files),
            "kinds": kinds,
            "last_ts": timeline[-1]["ts"] if timeline else None,
        })
    return {
        "version": 1,
        "last_built": _now_iso(),
        "projects": projects,
    }


def _load_project_names() -> list[str]:
    path = _registry_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    projects = data.get("projects", data) if isinstance(data, dict) else data
    if isinstance(projects, dict):
        return [
            str(name)
            for name, entry in projects.items()
            if name != "schema_version"
            and not (isinstance(entry, dict) and entry.get("status") not in (None, "active"))
        ]
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


def _write_project_indexes(project: str, files: dict[str, Any]) -> None:
    index_dir = _index_dir(project)
    _write_json(index_dir / "files.json", files)
    _write_json(index_dir / "search.json", build_search_index(files))
    _write_json(index_dir / "links.json", build_links_index(files))
    _write_timeline(index_dir / "timeline.jsonl", build_timeline(files))


def rebuild_project(project: str) -> dict[str, Any]:
    files = build_files_index(project)
    _write_project_indexes(project, files)
    return files


def rebuild_all() -> dict[str, Any]:
    project_indexes = {project: rebuild_project(project) for project in _load_project_names()}
    global_index = build_global_index(project_indexes)
    _write_json(_memory_root() / "index.json", global_index)
    return global_index


def _project_from_file(path: Path) -> str:
    resolved = path.expanduser().resolve()
    projects_root = _projects_root().resolve()
    relative = resolved.relative_to(projects_root)
    if not relative.parts:
        raise ValueError(f"file is not inside {projects_root}: {path}")
    return relative.parts[0]


def update_file(path: Path) -> dict[str, Any]:
    project = _project_from_file(path)
    return rebuild_project(project)


def query_project(project: str, **filters: str | None) -> list[dict[str, Any]]:
    path = _index_dir(project) / "files.json"
    if not path.exists():
        return []
    index = json.loads(path.read_text(encoding="utf-8"))
    records = index.get("files", [])
    for key, value in filters.items():
        if value is None:
            continue
        records = [record for record in records if str(record.get(key)) == value]
    return records


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    rebuild = subparsers.add_parser("rebuild", help="Rebuild project or global indexes")
    target = rebuild.add_mutually_exclusive_group(required=True)
    target.add_argument("--project")
    target.add_argument("--all", action="store_true")

    update = subparsers.add_parser("update", help="Update indexes for one Markdown file")
    update.add_argument("--file", required=True)

    query = subparsers.add_parser("query", help="Query a project files index")
    query.add_argument("--project", required=True)
    query.add_argument("--kind")
    query.add_argument("--severity")
    query.add_argument("--status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "rebuild":
        result = rebuild_all() if args.all else rebuild_project(args.project)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "update":
        result = update_file(Path(args.file))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "query":
        records = query_project(
            args.project,
            kind=args.kind,
            severity=args.severity,
            status=args.status,
        )
        print(json.dumps(records, ensure_ascii=False, sort_keys=True))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
