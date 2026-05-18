#!/usr/bin/env python3
"""Archive completed dispatch entries from MEMORY.md into monthly archives.

Default mode is dry-run. Use --commit to write MEMORY.md and
MEMORY_ARCHIVE_<YYYY_MM>.md files.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ARCHIVE_RE = re.compile(r"✅[^\n]*(?:MERGED|Done|PASS)", re.IGNORECASE)
ACTIVE_RE = re.compile(r"(?:📤\s*DISPATCHED|🚀\s*in flight|⏳\s*pending)", re.IGNORECASE)
ARCHIVED_RE = re.compile(r"✅\s*archived", re.IGNORECASE)
DATE_RE = re.compile(r"(20\d{2})[-_/](\d{2})[-_/]\d{2}")
HEADING_RE = re.compile(r"^#{1,6}\s+")
TOP_BULLET_RE = re.compile(r"^-\s+")


@dataclass(frozen=True)
class Block:
    start: int
    end: int
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class ArchiveEntry:
    task_id: str
    period: str
    block: Block
    archive_name: str

    @property
    def stub(self) -> str:
        return f"- {self.task_id}: ✅ archived → see {self.archive_name}"


def _default_period() -> str:
    return datetime.now().strftime("%Y_%m")


def _real_home() -> Path:
    return Path(os.environ.get("HOME") or Path.home()).expanduser()


def _current_project() -> str | None:
    context_path = _real_home() / ".agents" / "memory" / "machine" / "current_context.json"
    try:
        raw = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    project = raw.get("current_project")
    return project if isinstance(project, str) and project else None


def resolve_memory_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_path = os.environ.get("CLAWSEAT_MEMORY_MD")
    if env_path:
        return Path(env_path).expanduser().resolve()

    cwd_memory = Path.cwd() / "MEMORY.md"
    if cwd_memory.is_file():
        return cwd_memory.resolve()

    home = _real_home()
    project = _current_project()
    candidates: list[Path] = []
    if project:
        encoded = f"-Users-ywf--agents-workspaces-{project}-memory"
        candidates.append(home / ".claude" / "projects" / encoded / "memory" / "MEMORY.md")
        candidates.extend((home / ".claude" / "projects").glob(f"*{project}*memory/memory/MEMORY.md"))

    candidates.extend((home / ".claude" / "projects").glob("*/memory/MEMORY.md"))
    existing = [path for path in candidates if path.is_file()]
    if not existing:
        raise FileNotFoundError(
            "MEMORY.md not found; pass --memory-path or set CLAWSEAT_MEMORY_MD"
        )
    return max(existing, key=lambda path: path.stat().st_mtime).resolve()


def split_blocks(lines: list[str]) -> list[Block]:
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not TOP_BULLET_RE.match(line):
            index += 1
            continue
        start = index
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if TOP_BULLET_RE.match(next_line) or HEADING_RE.match(next_line) or next_line == "---":
                break
            index += 1
        blocks.append(Block(start=start, end=index, lines=lines[start:index]))
    return blocks


def extract_task_id(block_text: str) -> str:
    first_line = block_text.splitlines()[0].strip()
    link = re.search(r"\[([^\]]+)\]\([^)]+\)", first_line)
    if link:
        return link.group(1).removesuffix(".md")

    bullet = re.sub(r"^-\s+", "", first_line)
    before_colon = bullet.split(":", 1)[0].strip()
    if before_colon and len(before_colon) <= 120:
        return _clean_task_id(before_colon)

    token = bullet.split(maxsplit=1)[0] if bullet else "archived-entry"
    return _clean_task_id(token)


def _clean_task_id(value: str) -> str:
    cleaned = value.strip(" `[]()。，,;；")
    cleaned = re.sub(r"\.md$", "", cleaned)
    return cleaned or "archived-entry"


def extract_period(block_text: str, default_period: str) -> str:
    match = DATE_RE.search(block_text)
    if not match:
        return default_period
    return f"{match.group(1)}_{match.group(2)}"


def find_archive_entries(lines: list[str], default_period: str) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    for block in split_blocks(lines):
        text = block.text
        if not ARCHIVE_RE.search(text):
            continue
        if ARCHIVED_RE.search(text) or ACTIVE_RE.search(text):
            continue
        period = extract_period(text, default_period)
        archive_name = f"MEMORY_ARCHIVE_{period}.md"
        entries.append(
            ArchiveEntry(
                task_id=extract_task_id(text),
                period=period,
                block=block,
                archive_name=archive_name,
            )
        )
    return entries


def render_archived_memory(lines: list[str], entries: list[ArchiveEntry]) -> str:
    by_start = {entry.block.start: entry for entry in entries}
    skip_indexes = {
        index
        for entry in entries
        for index in range(entry.block.start + 1, entry.block.end)
    }
    rendered: list[str] = []
    for index, line in enumerate(lines):
        entry = by_start.get(index)
        if entry:
            rendered.append(entry.stub)
            continue
        if index in skip_indexes:
            continue
        rendered.append(line)
    return "\n".join(rendered).rstrip() + "\n"


def _archive_header(path: Path) -> str:
    period = path.stem.removeprefix("MEMORY_ARCHIVE_")
    return f"# Memory Archive {period}\n\n"


def append_archives(memory_path: Path, entries: list[ArchiveEntry]) -> list[Path]:
    touched: list[Path] = []
    by_period: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        by_period.setdefault(entry.period, []).append(entry)

    for period, period_entries in sorted(by_period.items()):
        archive_path = memory_path.with_name(f"MEMORY_ARCHIVE_{period}.md")
        existing = archive_path.read_text(encoding="utf-8") if archive_path.exists() else ""
        chunks: list[str] = []
        for entry in period_entries:
            if entry.task_id in existing:
                continue
            chunks.append(f"## {entry.task_id}\n\n{entry.block.text.rstrip()}\n")
        if not chunks:
            continue
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if existing else _archive_header(archive_path)
        with archive_path.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "\n".join(chunks))
            if not chunks[-1].endswith("\n\n"):
                handle.write("\n")
        touched.append(archive_path)
    return touched


def backup_memory(memory_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = memory_path.with_name(f"{memory_path.name}.bak.{stamp}")
    suffix = 1
    while backup.exists():
        backup = memory_path.with_name(f"{memory_path.name}.bak.{stamp}.{suffix}")
        suffix += 1
    backup.write_text(memory_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def archive(memory_path: Path, *, commit: bool, default_period: str) -> dict[str, object]:
    if not memory_path.is_file():
        raise FileNotFoundError(f"MEMORY.md not found: {memory_path}")

    if commit:
        with memory_path.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                original = handle.read()
                result = _archive_loaded(memory_path, original, commit=True, default_period=default_period)
                handle.seek(0)
                handle.truncate()
                handle.write(result["memory_text"])
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        result.pop("memory_text", None)
        return result

    with memory_path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            original = handle.read()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    result = _archive_loaded(memory_path, original, commit=False, default_period=default_period)
    result.pop("memory_text", None)
    return result


def _archive_loaded(memory_path: Path, original: str, *, commit: bool, default_period: str) -> dict[str, object]:
    lines = original.splitlines()
    entries = find_archive_entries(lines, default_period)
    rendered = render_archived_memory(lines, entries)
    backup_path: Path | None = None
    archives: list[Path] = []

    if commit and entries:
        backup_path = backup_memory(memory_path)
        archives = append_archives(memory_path, entries)

    line_count = len(rendered.splitlines())
    return {
        "mode": "commit" if commit else "dry-run",
        "memory_path": str(memory_path),
        "archive_count": len(entries),
        "line_count_after": line_count,
        "within_200_lines": line_count <= 200,
        "entries": [
            {
                "task_id": entry.task_id,
                "archive": entry.archive_name,
                "lines": entry.block.end - entry.block.start,
            }
            for entry in entries
        ],
        "backup": str(backup_path) if backup_path else None,
        "archives_written": [str(path) for path in archives],
        "memory_text": rendered,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive completed MEMORY.md dispatch entries into monthly archive files."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="show archive plan without writing (default)")
    mode.add_argument("--commit", action="store_true", help="write MEMORY.md and archive files")
    parser.add_argument("--memory-path", help="path to MEMORY.md; defaults to current ClawSeat memory")
    parser.add_argument(
        "--default-period",
        default=_default_period(),
        help="YYYY_MM archive period when an entry has no date (default: current month)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commit = bool(args.commit)
    try:
        memory_path = resolve_memory_path(args.memory_path)
        result = archive(memory_path, commit=commit, default_period=args.default_period)
    except Exception as exc:  # noqa: BLE001 CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if commit and not result["within_200_lines"]:
        print("error: MEMORY.md remains over 200 lines after archive", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
