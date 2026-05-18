#!/usr/bin/env python3
"""
extract_links.py — deterministic typed-link extraction for memory pages.

Reads a memory page (.md or .json), extracts entity references via regex
(zero LLM calls), and writes typed edges to two JSONL indexes:

    ~/.agents/memory/_links/<flat-source>.jsonl       (outgoing edges)
    ~/.agents/memory/_backlinks/<flat-target>.jsonl   (incoming edges)

Source slugs are paths relative to MEMORY_ROOT, sans extension. External
entities (task IDs, commits, URLs, ...) live in the namespace `entity:<type>:<value>`.

Usage:
    python3 extract_links.py --file <path> [--memory-dir <root>] [--quiet]

Idempotent: re-running on the same file updates the source's outgoing edges
and reconciles backlinks (removes stale entries, appends new).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _memory_paths import MEMORY_ROOT  # noqa: E402

# ── Edge-type regex patterns (deterministic, project-aware but generic) ────

DEFAULT_COMPONENT_SUFFIXES = ["Phasic", "Physics", "View", "Engine", "Layer", "Component"]
COMPONENT_CONFIG_TEXT = """[component_patterns]
# Default: arena/pretext-flow legacy suffixes.
# Override per-project in ~/.agents/memory/projects/<project>/component-patterns.toml
suffixes = ["Phasic", "Physics", "View", "Engine", "Layer", "Component"]
"""

BASE_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (edge_type, entity_namespace, compiled regex)
    ("references-task", "taskid", re.compile(
        r"\b([A-Z][A-Z0-9]+-\d+)\b"
        r"|\b(GH#\d+)\b"
        r"|(?<![\w/])(#\d+)\b"
    )),
    ("references-commit", "commit", re.compile(
        r"(?:^|(?<=\s))commit\s+([a-f0-9]{7,40})\b"
        r"|\(([a-f0-9]{7,40})\)(?=\s|$)"
        r"|\bmerged?\s+([a-f0-9]{7,40})\b"
        r"|\bcherry.pick(?:ed)?\s+([a-f0-9]{7,40})\b",
        re.IGNORECASE,
    )),
    ("references-file", "file", re.compile(r"\b([a-zA-Z][\w./-]*\.(?:tsx|ts|py|md|toml|sh|json|yaml|yml|sql|js))\b")),
    ("references-url", "url", re.compile(r"(https?://[^\s)\]\"<>]+)")),
    ("references-key", "key", re.compile(r"\[KEY:\s*([^\]]+)\]")),
    ("references-project", "project", re.compile(r"~/\.agents/memory/projects/([a-zA-Z][\w-]*)\b")),
]

_SNIPPET_RADIUS = 60
_FLAT_PATH_SEP = "__"
_FLAT_NS_SEP = "++"


def _flat(slug: str) -> str:
    """Encode a slug into a filesystem-safe flat name."""
    return slug.replace("/", _FLAT_PATH_SEP).replace(":", _FLAT_NS_SEP)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _source_slug(file_path: Path, memory_root: Path) -> str | None:
    """Derive source slug as MEMORY_ROOT-relative path, no extension.

    Returns None if file_path is not under memory_root.
    """
    try:
        rel = file_path.resolve().relative_to(memory_root.resolve())
    except ValueError:
        return None
    return str(rel.with_suffix(""))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _safe_component_suffixes(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    suffixes: list[str] = []
    for item in raw:
        if isinstance(item, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", item):
            suffixes.append(item)
    return suffixes


def _load_component_suffixes(project: str | None = None) -> list[str]:
    """Load component suffixes from project config, user config, or bundled defaults."""
    paths: list[Path] = []
    home = Path.home()
    if project:
        paths.append(home / ".agents" / "memory" / "projects" / project / "component-patterns.toml")
    user_config = home / ".agents" / "memory" / "config" / "component-patterns.toml"
    paths.append(user_config)

    for path in paths:
        if not path.exists():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        suffixes = _safe_component_suffixes(
            data.get("component_patterns", {}).get("suffixes", [])
        )
        if suffixes:
            return suffixes

    # Seed the user-level config as an editable documented default. Failure is
    # non-fatal because link extraction must not block memory writes.
    try:
        user_config.parent.mkdir(parents=True, exist_ok=True)
        if not user_config.exists():
            user_config.write_text(COMPONENT_CONFIG_TEXT, encoding="utf-8")
            os.chmod(user_config, 0o600)
    except OSError:
        pass
    return list(DEFAULT_COMPONENT_SUFFIXES)


def _component_pattern(project: str | None = None) -> tuple[str, str, re.Pattern]:
    suffixes = _load_component_suffixes(project=project)
    suffix_pattern = "|".join(re.escape(suffix) for suffix in suffixes)
    return (
        "references-component",
        "component",
        re.compile(rf"\b([A-Z][a-zA-Z0-9]+(?:{suffix_pattern}))\b"),
    )


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code block contents to avoid false-positive links."""
    out: list[str] = []
    in_block = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if not in_block:
            out.append(line)
    return "\n".join(out)


def _snippet(text: str, start: int, end: int) -> str:
    """Return ~120 char window around match, single-line, no leading/trailing ws."""
    s = max(0, start - _SNIPPET_RADIUS)
    e = min(len(text), end + _SNIPPET_RADIUS)
    window = text[s:e].replace("\n", " ").strip()
    return re.sub(r"\s+", " ", window)


def _match_value(match: re.Match) -> str:
    for value in match.groups():
        if value:
            return value
    return match.group(0)


def _dedup_edges(edges: list[dict]) -> list[dict]:
    seen: set[tuple[object, object, object]] = set()
    out: list[dict] = []
    for edge in edges:
        key = (
            edge.get("source") or edge.get("from"),
            edge.get("target") or edge.get("to"),
            edge.get("edge_type") or edge.get("type"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def _project_from_source(source: str | None) -> str | None:
    if not source:
        return None
    parts = source.split("/")
    if len(parts) >= 2 and parts[0] == "projects":
        return parts[1]
    return None


def extract_edges(*args: str, project: str | None = None) -> list[dict]:
    """Run all regex patterns over text. Returns deduped edges with snippets.

    Backward compatible forms:
      extract_edges(text)
      extract_edges(source, text, project="...")
    """
    if len(args) == 1:
        source = None
        text = args[0]
    elif len(args) == 2:
        source = args[0]
        text = args[1]
    else:
        raise TypeError("extract_edges() expects text or source, text")

    project = project or _project_from_source(source)
    clean_text = _strip_code_blocks(text)
    edges: list[dict] = []
    for edge_type, namespace, pattern in [*BASE_PATTERNS, _component_pattern(project=project)]:
        for match in pattern.finditer(clean_text):
            value = _match_value(match)
            target = f"entity:{namespace}:{value}"
            edge = {
                "to": target,
                "target": target,
                "type": edge_type,
                "edge_type": edge_type,
                "snippet": _snippet(clean_text, match.start(), match.end()),
            }
            if source:
                edge["source"] = source
            edges.append(edge)
    return _dedup_edges(edges)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return out


def _write_jsonl(path: Path, records: list[dict]) -> None:
    if not records:
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        return
    text = "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records) + "\n"
    _atomic_write(path, text)


def _backlinks_path(memory_root: Path, target: str) -> Path:
    return memory_root / "_backlinks" / f"{_flat(target)}.jsonl"


def _links_path(memory_root: Path, source: str) -> Path:
    return memory_root / "_links" / f"{_flat(source)}.jsonl"


def update_indexes(source: str, edges: list[dict], memory_root: Path) -> dict:
    """Reconcile both indexes for `source`.

    1. Read current outgoing edges (old)
    2. Compute diff: removed targets, added targets
    3. Write new outgoing index for `source`
    4. For each removed target: rewrite its backlinks file (drop this source)
    5. For each added target: append to its backlinks file

    Returns a summary of what changed.
    """
    links_path = _links_path(memory_root, source)
    old_edges = _read_jsonl(links_path)
    old_targets = {e.get("to") for e in old_edges if e.get("to")}
    new_targets = {e.get("to") for e in edges if e.get("to")}

    removed = old_targets - new_targets
    added = new_targets - old_targets
    timestamp = _now_iso()

    # New outgoing index includes timestamp + edges
    out_records = [
        {**edge, "from": source, "extracted_at": timestamp}
        for edge in edges
    ]
    _write_jsonl(links_path, out_records)

    # Drop this source from removed targets' backlinks
    for target in removed:
        bl_path = _backlinks_path(memory_root, target)
        existing = _read_jsonl(bl_path)
        retained = [r for r in existing if r.get("from") != source]
        _write_jsonl(bl_path, retained)

    # Append this source to added/updated targets' backlinks
    for edge in out_records:
        target = edge["to"]
        bl_path = _backlinks_path(memory_root, target)
        existing = _read_jsonl(bl_path)
        # Drop any prior entry from this source for this target (idempotency)
        existing = [r for r in existing if r.get("from") != source]
        existing.append({
            "from": source,
            "type": edge["type"],
            "snippet": edge["snippet"],
            "extracted_at": timestamp,
        })
        _write_jsonl(bl_path, existing)

    return {
        "source": source,
        "edges_total": len(edges),
        "targets_added": sorted(added),
        "targets_removed": sorted(removed),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract typed links from a memory page.")
    p.add_argument("--file", required=True, help="Path to memory page (.md or .json)")
    p.add_argument(
        "--memory-dir",
        default=str(MEMORY_ROOT),
        help=f"Memory root directory (default: {MEMORY_ROOT})",
    )
    p.add_argument("--quiet", action="store_true", help="Suppress stdout summary")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    file_path = Path(args.file).expanduser()
    memory_root = Path(args.memory_dir).expanduser().resolve()

    if not file_path.is_file():
        print(f"error: not a file: {file_path}", file=sys.stderr)
        return 2

    source = _source_slug(file_path, memory_root)
    if source is None:
        print(f"error: file is not under memory root {memory_root}: {file_path}", file=sys.stderr)
        return 2

    text = _read_text(file_path)
    edges = extract_edges(source, text) if text else []
    summary = update_indexes(source, edges, memory_root)

    if not args.quiet:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
