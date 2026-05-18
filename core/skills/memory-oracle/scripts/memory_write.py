#!/usr/bin/env python3
"""
memory_write.py — write a structured memory fact to the knowledge base.

Usage:
    python3 memory_write.py \\
        --kind decision \\
        --project install \\
        --title "Use option B" \\
        --body "We chose B because..." \\
        --author planner \\
        [--evidence '[{"type":"file","value":"SPEC.md","trust":"high","source_url":"https://..."}]'] \\
        [--related-task-ids T-001,T-002] \\
        [--confidence high|medium|low] \\
        [--source write_api] \\
        [--supersedes <old-id>] \\
        [--seats seat1,seat2]    # whitelist for author governance check \\
        [--memory-dir ~/.agents/memory]  # override root \\
        [--dry-run]              # validate but do not write

Exit codes:
    0  success (or dry-run validation passed)
    1  schema validation failed (hard error)
    2  bad CLI usage / invalid JSON
    Stdout: JSON with {id, path, warnings} on success, or record JSON on dry-run.
    Stderr: warnings (soft governance) or error messages.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_CORE_LIB = _SCRIPTS.parents[2] / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))

from _memory_paths import (  # noqa: E402
    MEMORY_ROOT,
    KIND_SUBDIRS,
    SHARED_KIND_SUBDIRS,
    generate_id,
    reflections_path,
)
from _memory_schema import SchemaError, make_record, validate  # noqa: E402
from utils import now_iso  # noqa: E402


DROP_KINDS = frozenset(KIND_SUBDIRS.keys())


def _fact_path(kind: str, project: str, fact_id: str, memory_root: Path) -> Path:
    """Resolve storage path relative to a given memory_root."""
    if project == "_shared":
        subdir_name = SHARED_KIND_SUBDIRS.get(kind, f"{kind}s")
        return memory_root / "shared" / subdir_name / f"{fact_id}.json"
    if kind == "reflection":
        return reflections_path(project, memory_root=memory_root)
    subdir_name = KIND_SUBDIRS.get(kind)
    if subdir_name:
        return memory_root / "projects" / project / subdir_name / f"{fact_id}.json"
    return memory_root / "projects" / project / f"{fact_id}.json"


def _write_fact(record: dict, path: Path) -> None:
    _atomic_write_text(
        path,
        json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False),
    )


def _append_jsonl(record: dict, path: Path) -> None:
    """Append one JSON record as a single line to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _default_memory_root() -> Path:
    agent_home = os.environ.get("AGENT_HOME")
    if agent_home:
        return Path(agent_home).expanduser().resolve() / ".agents" / "memory"
    return MEMORY_ROOT


def _load_json(path: Path) -> dict | None:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    try:
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _index_lock_path(index_path: Path) -> Path:
    return index_path.with_name(f"{index_path.name}.lock")


def _update_memory_index(memory_root: Path, entry: dict) -> Path:
    index_path = memory_root / "index.json"
    lock_path = _index_lock_path(index_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = _load_json(index_path) or {}
        if not isinstance(current, dict):
            current = {}

        notes = current.get("memory_notes")
        if not isinstance(notes, list):
            notes = []
        notes = list(notes)
        notes.append(entry)

        current["memory_notes"] = notes
        current["memory_notes_updated_at"] = now_iso()
        current["memory_notes_count"] = len(notes)
        _atomic_write_text(
            index_path,
            json.dumps(current, indent=2, ensure_ascii=False, sort_keys=True),
        )
        fcntl.flock(lock, fcntl.LOCK_UN)
    return index_path


def _filename_stamp(ts: str) -> str:
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return (
            ts.strip()
            .replace(":", "-")
            .replace("+", "-")
            .replace("/", "-")
            .replace(" ", "_")
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return f"{parsed.strftime('%Y-%m-%dT%H-%M-%S')}.{parsed.microsecond * 1000:09d}Z"


def _drop_filename_stamp() -> str:
    ns = time.time_ns()
    dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
    return f"{dt.strftime('%Y-%m-%dT%H-%M-%S')}-{ns % 1_000_000_000:09d}"


def _derive_note_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        return stripped or fallback
    return fallback


def _read_drop_content(args: argparse.Namespace) -> tuple[str, str]:
    if args.content_file:
        content_path = Path(args.content_file).expanduser()
        try:
            return content_path.read_text(encoding="utf-8"), str(content_path)
        except OSError as exc:
            raise ValueError(f"error: unable to read --content-file {content_path}: {exc}") from exc
    return sys.stdin.read(), "stdin"


def _build_markdown_note(metadata: dict[str, object], content: str) -> str:
    header_lines = ["---"]
    for key, value in metadata.items():
        if value is None:
            continue
        header_lines.append(f"{key}: {value}")
    header_lines.append("---")
    body = content.rstrip("\n")
    if body:
        return "\n".join(header_lines + ["", body, ""])
    return "\n".join(header_lines + ["", ""])


def _write_markdown_note(path: Path, metadata: dict[str, object], content: str) -> None:
    _atomic_write_text(path, _build_markdown_note(metadata, content))


def _update_scan_index(path: Path) -> None:
    if path.suffix != ".md":
        return
    try:
        subprocess.run(
            [
                sys.executable,
                str(_SCRIPTS / "scan_index.py"),
                "update",
                "--file",
                str(path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        _ = exc


def _update_link_graph(path: Path, memory_root: Path) -> None:
    """Run extract_links.py to refresh typed-link / backlink indexes for this page.

    Failures are silenced — link graph is a best-effort derivative index, never
    blocking on writes.
    """
    if path.suffix not in (".md", ".json"):
        return
    try:
        subprocess.run(
            [
                sys.executable,
                str(_SCRIPTS / "extract_links.py"),
                "--file",
                str(path),
                "--memory-dir",
                str(memory_root),
                "--quiet",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        _ = exc


def _append_memory_note_index(
    memory_root: Path,
    *,
    note_id: str,
    project: str,
    kind: str,
    title: str,
    author: str,
    ts: str,
    created_at: str,
    filename_stamp: str,
    note_path: Path,
    content_source: str,
    content_bytes: int,
) -> Path:
    return _update_memory_index(memory_root, {
        "id": note_id,
        "project": project,
        "kind": kind,
        "title": title,
        "author": author,
        "ts": ts,
        "created_at": created_at,
        "filename_stamp": filename_stamp,
        "path": str(note_path),
        "content_source": content_source,
        "content_bytes": content_bytes,
        "source": "drop_cli",
    })


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Write a memory fact to the structured knowledge base."
    )
    p.add_argument("--kind", required=True, help="Fact kind (decision, finding, …)")
    p.add_argument("--project", required=True, help="Project name or '_shared'")
    p.add_argument("--title", default=None, help="Short title (required for legacy record mode)")
    p.add_argument("--body", default="", help="Long-form body (markdown OK)")
    p.add_argument("--author", default=None, help="Author seat name (legacy mode required; drop mode defaults to ancestor)")
    content_group = p.add_mutually_exclusive_group(required=False)
    content_group.add_argument(
        "--content-file",
        help="Drop mode: markdown content file to write into projects/<project>/<kind>/",
    )
    content_group.add_argument(
        "--content-stdin",
        action="store_true",
        help="Drop mode: read markdown content from stdin",
    )
    p.add_argument(
        "--iso",
        default=None,
        help="Drop mode: override the timestamp used in the markdown filename and note metadata",
    )
    p.add_argument(
        "--evidence",
        default="[]",
        help=(
            "JSON array of evidence items. "
            'library_knowledge/finding require trust+source_url on each item. '
            'Example: \'[{"type":"file","value":"SPEC.md","trust":"high","source_url":"https://..."}]\''
        ),
    )
    p.add_argument(
        "--related-task-ids",
        default="",
        help="Comma-separated task IDs (e.g. T-001,T-002)",
    )
    p.add_argument(
        "--confidence",
        default="medium",
        choices=["high", "medium", "low"],
        help="Confidence level (default: medium)",
    )
    p.add_argument(
        "--source",
        default="write_api",
        choices=["scanner", "write_api", "reflection", "event_derived", "research"],
        help="Provenance source (default: write_api)",
    )
    p.add_argument("--supersedes", default=None, help="ID of the record this supersedes")
    p.add_argument(
        "--seats",
        default="",
        help="Comma-separated authorised seat names for author governance (soft check)",
    )
    p.add_argument(
        "--memory-dir",
        default=str(_default_memory_root()),
        help=f"Memory root directory (default: {MEMORY_ROOT})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate schema and print the record without writing to disk",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress stdout output")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    drop_mode = bool(args.content_file or args.content_stdin)
    if drop_mode:
        if args.kind not in DROP_KINDS:
            print(
                "error: drop mode only supports kinds: decision, delivery, issue, finding",
                file=sys.stderr,
            )
            return 2

        try:
            content, content_source = _read_drop_content(args)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        note_ts = args.iso or now_iso()
        created_at = now_iso()
        filename_stamp = _filename_stamp(args.iso) if args.iso else _drop_filename_stamp()
        note_id = f"{args.project}-{args.kind}-{filename_stamp}-PID{os.getpid()}"
        out_path = (
            Path(args.memory_dir).expanduser().resolve()
            / "projects"
            / args.project
            / args.kind
            / f"{note_id}.md"
        )
        title = args.title or _derive_note_title(content, fallback=args.kind)
        author = args.author or "ancestor"
        warnings: list[str] = []
        known_authors: list[str] | None = (
            [s.strip() for s in args.seats.split(",") if s.strip()] or None
        )
        if known_authors is not None and author not in known_authors:
            warnings.append(
                f"author {author!r} is not in seats whitelist {known_authors!r}"
            )
        if args.dry_run:
            if not args.quiet:
                print(str(out_path))
            return 0

        metadata = {
            "schema_version": 1,
            "format": "markdown_note",
            "id": note_id,
            "project": args.project,
            "kind": args.kind,
            "title": title,
            "author": author,
            "ts": note_ts,
            "created_at": created_at,
            "filename_stamp": filename_stamp,
            "content_source": content_source,
        }
        _write_markdown_note(out_path, metadata, content)
        _update_scan_index(out_path)
        _drop_memory_root = Path(args.memory_dir).expanduser().resolve()
        _update_link_graph(out_path, _drop_memory_root)
        _append_memory_note_index(
            _drop_memory_root,
            note_id=note_id,
            project=args.project,
            kind=args.kind,
            title=title,
            author=author,
            ts=note_ts,
            created_at=created_at,
            filename_stamp=filename_stamp,
            note_path=out_path,
            content_source=content_source,
            content_bytes=len(content.encode("utf-8")),
        )
        if not args.quiet:
            print(str(out_path))
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0

    # ── Parse evidence JSON ──────────────────────────────────────────
    try:
        evidence: list[dict] = json.loads(args.evidence)
    except json.JSONDecodeError as exc:
        print(f"error: --evidence is not valid JSON: {exc}", file=sys.stderr)
        return 2

    if not isinstance(evidence, list):
        print("error: --evidence must be a JSON array", file=sys.stderr)
        return 2

    # ── Parse related_task_ids ───────────────────────────────────────
    related = [t.strip() for t in args.related_task_ids.split(",") if t.strip()]

    # ── Parse seats for soft author governance ───────────────────────
    known_authors: list[str] | None = (
        [s.strip() for s in args.seats.split(",") if s.strip()] or None
    )

    if args.title is None:
        print("error: --title is required in legacy record mode", file=sys.stderr)
        return 2
    if args.author is None:
        print("error: --author is required in legacy record mode", file=sys.stderr)
        return 2

    ts = now_iso()
    fact_id = generate_id(args.kind, args.project, args.title)

    record = make_record(
        kind=args.kind,
        project=args.project,
        author=args.author,
        ts=ts,
        title=args.title,
        body=args.body,
        fact_id=fact_id,
        evidence=evidence,
        related_task_ids=related,
        supersedes=args.supersedes,
        confidence=args.confidence,
        source=args.source,
    )

    # ── Validate (hard failures raise, soft failures return warnings) ─
    try:
        warnings = validate(record, known_authors=known_authors)
    except SchemaError as exc:
        print(f"error: schema validation failed: {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    if args.dry_run:
        if not args.quiet:
            print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0

    # ── Write to disk ────────────────────────────────────────────────
    memory_root = Path(args.memory_dir).expanduser().resolve()
    out_path = _fact_path(args.kind, args.project, fact_id, memory_root)

    if args.kind == "reflection":
        _append_jsonl(record, out_path)
    else:
        _write_fact(record, out_path)
        _update_link_graph(out_path, memory_root)

    if not args.quiet:
        result = {
            "id": fact_id,
            "path": str(out_path),
            "warnings": warnings,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
