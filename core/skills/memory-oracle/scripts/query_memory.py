#!/usr/bin/env python3
"""
query_memory.py — query the Memory CC knowledge base.

Modes:
  New-layout list (v2):
     python3 query_memory.py --project install --kind decision
     python3 query_memory.py --project install --kind decision --since 2026-04-01
     python3 query_memory.py --kind finding --since 2026-04-15

  Direct read (fast, key-value) — reads machine/*.json then falls back to flat *.json:
     python3 query_memory.py --key credentials.keys.MINIMAX_API_KEY
     python3 query_memory.py --search feishu
     python3 query_memory.py --file openclaw --section feishu

  Ask Memory CC TUI (deprecated compatibility path):
     python3 query_memory.py --ask "designer seat uses which provider?" --profile <p.toml>

Zero third-party dependencies.  Supports both old flat layout and new v3 machine/ layout.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from pathlib import Path

HOME = Path.home()
DEFAULT_MEMORY_DIR = HOME / ".agents" / "memory"

# Ensure sibling scripts (e.g. _memory_paths) are importable
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
_CORE_LIB = _SCRIPTS.parents[2] / "lib"
if str(_CORE_LIB) not in sys.path:
    sys.path.insert(0, str(_CORE_LIB))
from utils import now_iso  # noqa: E402


# ── Low-level JSON helpers ────────────────────────────────────────────────────


def _load_json(path: Path) -> dict | None:
    """Load a JSON file from a full path."""
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _index_lock_path(index_path: Path) -> Path:
    return index_path.with_name(f"{index_path.name}.lock")


def _load_locked_json(path: Path) -> dict | None:
    lock_path = _index_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        try:
            return _load_json(path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _load_root_index(memory_dir: Path) -> dict | None:
    return _load_locked_json(memory_dir / "index.json")


def _load_jsonl(path: Path) -> list[dict]:
    """Load all valid records from a JSONL (newline-delimited JSON) file."""
    if not path.is_file():
        return []
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rec = json.loads(line)
                    if isinstance(rec, dict):
                        records.append(rec)
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return records


def load_memory_file(memory_dir: Path, name: str) -> dict | None:
    """Load a named memory file.

    Checks machine/<name>.json first (v3 layout), then falls back to the
    flat <name>.json layout so old --key calls keep working.
    """
    machine_path = memory_dir / "machine" / f"{name}.json"
    if machine_path.is_file():
        return _load_json(machine_path)
    flat_path = memory_dir / f"{name}.json"
    if flat_path.is_file():
        return _load_json(flat_path)
    return None


def _split_markdown_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:])
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    return {}, text


def _derive_note_title(meta: dict[str, str], body: str, fallback: str) -> str:
    title = meta.get("title")
    if title:
        return title
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
        return stripped or fallback
    return fallback


def _load_markdown_note(path: Path, *, project: str | None = None, kind: str | None = None) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = _split_markdown_front_matter(text)
    note_project = meta.get("project") or project
    note_kind = meta.get("kind") or kind
    note = {
        "schema_version": int(meta.get("schema_version", "1")) if meta.get("schema_version", "1").isdigit() else 1,
        "format": meta.get("format", "markdown_note"),
        "id": meta.get("id", path.stem),
        "project": note_project,
        "kind": note_kind,
        "title": _derive_note_title(meta, body, fallback=path.stem),
        "author": meta.get("author"),
        "ts": meta.get("ts") or meta.get("created_at"),
        "created_at": meta.get("created_at"),
        "filename_stamp": meta.get("filename_stamp"),
        "content_source": meta.get("content_source"),
        "body": body.rstrip("\n"),
        "path": str(path),
        "source": meta.get("source", "drop_cli"),
    }
    return note


def _note_map_key(record: dict) -> str | None:
    path = record.get("path")
    return path if isinstance(path, str) and path else None


def _upsert_note(note_map: dict[str, dict], record: dict) -> None:
    key = _note_map_key(record)
    if key is None:
        return
    existing = note_map.get(key)
    if existing is None:
        note_map[key] = record
        return
    existing.update(record)


def _result_sort_key(record: dict) -> tuple[str, str, str]:
    ts = record.get("ts") or record.get("created_at") or record.get("scanned_at") or ""
    path = record.get("path") or ""
    ident = record.get("id") or record.get("title") or ""
    return (str(ts), str(path), str(ident))


def _matches_list_filters(
    record: dict,
    *,
    project: str | None,
    kind: str | None,
    since: str | None,
) -> bool:
    if project is not None and record.get("project") != project:
        return False
    if kind is not None and record.get("kind") != kind:
        return False
    if since:
        ts = record.get("ts") or record.get("created_at") or record.get("scanned_at")
        if not isinstance(ts, str) or ts < since:
            return False
    return True


def walk_path(data: dict | list, path_parts: list[str]) -> object | None:
    """Walk a dotted path through nested dict/list."""
    current: object = data
    for part in path_parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


# ── Existing command handlers (backward-compatible) ──────────────────────────


def cmd_key(memory_dir: Path, key: str) -> int:
    """Read a dotted path like 'credentials.keys.MINIMAX_API_KEY.value'."""
    parts = key.split(".")
    if not parts:
        print("error: empty key", file=sys.stderr)
        return 2
    file_name = parts[0]
    data = load_memory_file(memory_dir, file_name)
    if data is None:
        print(
            f"error: memory file not found: {file_name}.json "
            f"(checked machine/ and flat layout under {memory_dir})",
            file=sys.stderr,
        )
        return 1
    if len(parts) == 1:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    value = walk_path(data, parts[1:])
    if value is None:
        print(f"not_found: {key}", file=sys.stderr)
        return 1
    if isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2, ensure_ascii=False))
    else:
        print(value)
    return 0


def cmd_file(memory_dir: Path, name: str, section: str | None) -> int:
    data = load_memory_file(memory_dir, name)
    if data is None:
        print(
            f"error: memory file not found: {name}.json "
            f"(checked machine/ and flat layout under {memory_dir})",
            file=sys.stderr,
        )
        return 1
    if section:
        value = walk_path(data, section.split("."))
        if value is None:
            print(f"not_found: {name}.{section}", file=sys.stderr)
            return 1
        data = value  # type: ignore
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def flatten(obj: object, prefix: str = "") -> list[tuple[str, object]]:
    """Flatten nested dict/list into (dotted_path, value) pairs."""
    out: list[tuple[str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                out.extend(flatten(v, key))
            else:
                out.append((key, v))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}.{i}" if prefix else str(i)
            if isinstance(v, (dict, list)):
                out.extend(flatten(v, key))
            else:
                out.append((key, v))
    return out


def _search_dir(term_lower: str, dir_path: Path, *, label_prefix: str = "") -> list[dict]:
    """Search all *.json files in a directory (non-recursive)."""
    matches: list[dict] = []
    if not dir_path.is_dir():
        return matches
    for json_path in sorted(dir_path.glob("*.json")):
        if json_path.stem == "index":
            continue
        data = _load_json(json_path)
        if data is None:
            continue
        label = f"{label_prefix}{json_path.stem}" if label_prefix else json_path.stem
        for path, value in flatten(data):
            key_hit = term_lower in path.lower()
            val_hit = term_lower in str(value).lower()
            if key_hit or val_hit:
                matches.append({
                    "file": label,
                    "path": path,
                    "value": str(value)[:200],
                    "match": "key" if key_hit else "value",
                })
    return matches


def cmd_search(memory_dir: Path, term: str, *, files: list[str] | None = None) -> int:
    """Case-insensitive search across memory files.

    Searches machine/ (v3 layout) and flat *.json (v1 layout).
    When --files is given, restricts to those names in machine/ or flat layout.
    """
    term_lower = term.lower()
    matches: list[dict] = []

    if files:
        for fname in files:
            data = load_memory_file(memory_dir, fname)
            if data is None:
                continue
            for path, value in flatten(data):
                key_hit = term_lower in path.lower()
                val_hit = term_lower in str(value).lower()
                if key_hit or val_hit:
                    matches.append({
                        "file": fname,
                        "path": path,
                        "value": str(value)[:200],
                        "match": "key" if key_hit else "value",
                    })
    else:
        # Search machine/ dir (v3 layout)
        matches.extend(_search_dir(term_lower, memory_dir / "machine", label_prefix="machine/"))
        # Search flat layout (v1, skip machine/ duplicates by stem)
        machine_stems = {
            p.stem for p in (memory_dir / "machine").glob("*.json")
        } if (memory_dir / "machine").is_dir() else set()
        for json_path in sorted(memory_dir.glob("*.json")):
            if json_path.stem in ("index", "response") or json_path.stem in machine_stems:
                continue
            data = _load_json(json_path)
            if data is None:
                continue
            for path, value in flatten(data):
                key_hit = term_lower in path.lower()
                val_hit = term_lower in str(value).lower()
                if key_hit or val_hit:
                    matches.append({
                        "file": json_path.stem,
                        "path": path,
                        "value": str(value)[:200],
                        "match": "key" if key_hit else "value",
                    })

    if not matches:
        print(f"no matches for: {term}", file=sys.stderr)
        return 1
    print(json.dumps({"term": term, "count": len(matches), "matches": matches}, indent=2, ensure_ascii=False))
    return 0


def cmd_status(memory_dir: Path) -> int:
    """Print memory DB status showing both v1 and v3 layout files."""
    if not memory_dir.is_dir():
        print(json.dumps({"exists": False, "path": str(memory_dir)}, indent=2))
        return 1
    index_data = _load_root_index(memory_dir)
    flat_files = sorted(p.name for p in memory_dir.glob("*.json"))
    machine_files = sorted(
        p.name for p in (memory_dir / "machine").glob("*.json")
    ) if (memory_dir / "machine").is_dir() else []
    projects = sorted(
        p.name for p in (memory_dir / "projects").iterdir() if p.is_dir()
    ) if (memory_dir / "projects").is_dir() else []
    result = {
        "exists": True,
        "path": str(memory_dir),
        "flat_files": flat_files,
        "machine_files": machine_files,
        "projects": projects,
        "index": index_data,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# ── New layout list command ───────────────────────────────────────────────────


def cmd_list(
    memory_dir: Path,
    *,
    project: str | None,
    kind: str | None,
    since: str | None,
) -> int:
    """List facts from the v3 structured knowledge base.

    Examples:
        --project install --kind decision
        --project install --kind decision --since 2026-04-01
        --kind finding
    """
    try:
        from _memory_paths import KIND_SUBDIRS, SHARED_KIND_SUBDIRS
    except ImportError:
        KIND_SUBDIRS = {
            "decision": "decisions",
            "delivery": "deliveries",
            "issue": "issues",
            "finding": "findings",
        }
        SHARED_KIND_SUBDIRS = {
            "library_knowledge": "library_knowledge",
            "pattern": "patterns",
            "example": "examples",
        }

    # M2 project-scanner kinds: stored as projects/<proj>/<kind>.json (single file)
    M2_KINDS: frozenset[str] = frozenset({
        "runtime", "tests", "deploy", "ci", "lint",
        "structure", "env_templates", "dev_env",
    })

    results: list[dict] = []
    note_map: dict[str, dict] = {}

    root_index = _load_root_index(memory_dir)
    if isinstance(root_index, dict):
        notes = root_index.get("memory_notes")
        if isinstance(notes, list):
            for note in notes:
                if isinstance(note, dict):
                    _upsert_note(note_map, note)

    def _collect_dir(d: Path) -> None:
        if not d.is_dir():
            return
        for f in sorted(d.glob("*.json")):
            rec = _load_json(f)
            if isinstance(rec, dict):
                results.append(rec)

    def _collect_markdown_dir(d: Path, *, default_project: str | None = None, default_kind: str | None = None) -> None:
        if not d.is_dir():
            return
        for f in sorted(d.glob("*.md")):
            note = _load_markdown_note(f, project=default_project, kind=default_kind)
            if isinstance(note, dict):
                _upsert_note(note_map, note)

    def _collect_project_kind(proj_name: str, kind_name: str) -> None:
        """Collect facts for a (project, kind) pair, routing JSONL kinds correctly."""
        proj_path = memory_dir / "projects" / proj_name

        if kind_name == "reflection":
            # SPEC §3: projects/<proj>/reflections.jsonl (JSONL, append-only)
            results.extend(_load_jsonl(proj_path / "reflections.jsonl"))
            return

        if kind_name == "event":
            # SPEC §3: root events.log (JSONL, append-only) — not project-scoped
            return

        if kind_name in M2_KINDS:
            # M2 scanner kinds: single file projects/<proj>/<kind>.json
            f = proj_path / f"{kind_name}.json"
            if f.is_file():
                rec = _load_json(f)
                if isinstance(rec, dict):
                    results.append(rec)
            return

        if proj_name == "_shared":
            subdir = SHARED_KIND_SUBDIRS.get(kind_name, f"{kind_name}s")
            _collect_dir(memory_dir / "shared" / subdir)
            _collect_markdown_dir(proj_path / kind_name, default_project=proj_name, default_kind=kind_name)
            return

        subdir = KIND_SUBDIRS.get(kind_name)
        if subdir:
            _collect_dir(proj_path / subdir)
            _collect_markdown_dir(proj_path / kind_name, default_project=proj_name, default_kind=kind_name)
        else:
            _collect_dir(proj_path)
            _collect_markdown_dir(proj_path / kind_name, default_project=proj_name, default_kind=kind_name)

    if kind == "event":
        # Global JSONL — project arg is ignored for event
        results.extend(_load_jsonl(memory_dir / "events.log"))

    elif project and kind:
        _collect_project_kind(project, kind)

    elif project:
        # All kinds in a project (JSON subdirs + JSONL reflections)
        proj_root = memory_dir / "projects" / project
        if proj_root.is_dir():
            for entry in sorted(proj_root.iterdir()):
                if entry.is_dir():
                    _collect_dir(entry)
                    _collect_markdown_dir(entry, default_project=project, default_kind=entry.name)
                elif entry.name == "reflections.jsonl":
                    results.extend(_load_jsonl(entry))
                elif entry.suffix == ".json":
                    rec = _load_json(entry)
                    if isinstance(rec, dict):
                        results.append(rec)

    elif kind:
        # Across all projects for this kind
        projects_root = memory_dir / "projects"
        if projects_root.is_dir():
            for proj_dir in sorted(projects_root.iterdir()):
                if proj_dir.is_dir():
                    _collect_project_kind(proj_dir.name, kind)
        # Also check shared for shared-scoped kinds
        if kind in SHARED_KIND_SUBDIRS:
            _collect_dir(memory_dir / "shared" / SHARED_KIND_SUBDIRS[kind])
        if kind in KIND_SUBDIRS and projects_root.is_dir():
            for proj_dir in sorted(projects_root.iterdir()):
                if proj_dir.is_dir():
                    _collect_markdown_dir(
                        proj_dir / kind,
                        default_project=proj_dir.name,
                        default_kind=kind,
                    )

    else:
        # --since only: scan all projects, all kinds (JSON + JSONL)
        projects_root = memory_dir / "projects"
        if projects_root.is_dir():
            for proj_dir in sorted(projects_root.iterdir()):
                if proj_dir.is_dir():
                    for entry in sorted(proj_dir.rglob("*.json")):
                        rec = _load_json(entry)
                        if isinstance(rec, dict):
                            results.append(rec)
                    results.extend(_load_jsonl(proj_dir / "reflections.jsonl"))
                    for entry in sorted(proj_dir.iterdir()):
                        if entry.is_dir():
                            _collect_markdown_dir(entry, default_project=proj_dir.name, default_kind=entry.name)
        results.extend(_load_jsonl(memory_dir / "events.log"))

    results.extend(note_map.values())
    project_filter = None if kind == "event" else project
    results = [r for r in results if _matches_list_filters(r, project=project_filter, kind=kind, since=since)]
    results.sort(key=_result_sort_key)

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if results else 1


# ── Ask handler (unchanged from v1) ──────────────────────────────────────────


def cmd_ask(question: str, *, profile_path: str | None, timeout: float) -> int:
    """Deprecated --ask path: keep the CLI entrypoint but stop dispatching."""
    print(
        "warning: --ask is deprecated; use --project/--kind listing or memory_deliver.py",
        file=sys.stderr,
    )
    return 2


# ── Link graph: typed-link / backlink queries (P1 memory graph) ──────────

_FLAT_PATH_SEP = "__"
_FLAT_NS_SEP = "++"


def _flat_slug(slug: str) -> str:
    return slug.replace("/", _FLAT_PATH_SEP).replace(":", _FLAT_NS_SEP)


def _normalise_slug(slug: str, memory_dir: Path) -> str:
    """Accept slug, slug.md, or absolute path; return MEMORY-relative slug w/o ext."""
    s = slug.strip()
    if s.startswith("entity:"):
        return s
    p = Path(s).expanduser()
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(memory_dir.resolve())
            return str(rel.with_suffix(""))
        except ValueError:
            pass
    if s.endswith((".md", ".json")):
        s = s.rsplit(".", 1)[0]
    return s


def _load_outgoing(memory_dir: Path, slug: str) -> list[dict]:
    path = memory_dir / "_links" / f"{_flat_slug(slug)}.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _load_incoming(memory_dir: Path, slug: str) -> list[dict]:
    path = memory_dir / "_backlinks" / f"{_flat_slug(slug)}.jsonl"
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def cmd_backlinks(memory_dir: Path, slug: str) -> int:
    """List all pages that link to this slug. JSON output."""
    norm = _normalise_slug(slug, memory_dir)
    incoming = _load_incoming(memory_dir, norm)
    print(json.dumps({
        "target": norm,
        "incoming_count": len(incoming),
        "incoming": incoming,
    }, indent=2, ensure_ascii=False))
    return 0 if incoming else 0  # zero is success even if no backlinks


def cmd_graph(memory_dir: Path, slug: str, depth: int) -> int:
    """BFS from slug up to depth N; output node + edge list. JSON output."""
    norm = _normalise_slug(slug, memory_dir)
    visited: set[str] = {norm}
    edges: list[dict] = []
    frontier: list[str] = [norm]

    for level in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            for edge in _load_outgoing(memory_dir, node):
                target = edge.get("to")
                if not target:
                    continue
                edges.append({
                    "from": node,
                    "to": target,
                    "type": edge.get("type"),
                    "snippet": edge.get("snippet"),
                    "depth": level + 1,
                })
                if target not in visited:
                    visited.add(target)
                    next_frontier.append(target)
        frontier = next_frontier
        if not frontier:
            break

    print(json.dumps({
        "root": norm,
        "depth": depth,
        "node_count": len(visited),
        "edge_count": len(edges),
        "nodes": sorted(visited),
        "edges": edges,
    }, indent=2, ensure_ascii=False))
    return 0


def verify_claims(response: dict, memory_dir: Path) -> dict:
    """Verify each claim's evidence against disk JSON files."""
    claims = response.get("claims")
    if claims is None:
        legacy_sources = response.get("sources", [])
        return {
            "all_verified": None,
            "reason": "legacy_schema_no_evidence",
            "legacy_sources": legacy_sources,
        }
    if not isinstance(claims, list):
        return {"all_verified": False, "reason": "claims_not_list"}

    results = []
    all_ok = True
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict):
            results.append({"index": i, "verified": False, "reason": "claim_not_dict"})
            all_ok = False
            continue
        statement = claim.get("statement", "")
        evidence_list = claim.get("evidence", [])
        if not evidence_list:
            results.append({
                "index": i,
                "statement": statement[:80],
                "verified": False,
                "reason": "no_evidence",
            })
            all_ok = False
            continue
        mismatches = []
        for ev in evidence_list:
            fname = ev.get("file", "")
            path = ev.get("path", "")
            expected = ev.get("expected_value")
            fname = os.path.basename(fname)
            if fname.endswith(".json"):
                fname = fname[:-5]
            if path:
                path = path.strip()
                if path.startswith("$."):
                    path = path[2:]
                elif path.startswith("$"):
                    path = path[1:].lstrip(".")
                path = path.lstrip("/").replace("/", ".")
                path = path.replace("[", ".").replace("]", "").replace("'", "").replace('"', "")
                while ".." in path:
                    path = path.replace("..", ".")
                path = path.strip(".")

            data = load_memory_file(memory_dir, fname)
            if data is None:
                mismatches.append({"file": fname, "path": path, "reason": "file_not_found"})
                continue
            actual = walk_path(data, path.split(".")) if path else data
            if actual != expected:
                mismatches.append({
                    "file": fname,
                    "path": path,
                    "expected": expected,
                    "actual": actual,
                    "reason": "mismatch" if actual is not None else "path_not_found",
                })
        verified = len(mismatches) == 0
        results.append({
            "index": i,
            "statement": statement[:80],
            "verified": verified,
            "mismatches": mismatches,
        })
        if not verified:
            all_ok = False
    return {"all_verified": all_ok, "claim_results": results}


# ── Argument parsing ──────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Query the Memory CC knowledge base (v1 and v3 layouts).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (v3 new-layout list):
  query_memory.py --project install --kind decision
  query_memory.py --project install --kind decision --since 2026-04-01
  query_memory.py --kind finding --since 2026-04-15

Examples (v1 backward-compatible):
  query_memory.py --key credentials.keys.MINIMAX_API_KEY
  query_memory.py --search feishu
  query_memory.py --file openclaw --section feishu
  query_memory.py --status
""",
    )
    p.add_argument(
        "--memory-dir",
        default=str(DEFAULT_MEMORY_DIR),
        help=f"Memory DB root (default: {DEFAULT_MEMORY_DIR})",
    )

    # ── v1 backward-compatible modes (mutually exclusive) ──────────────────
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument("--key", help="Dotted path, e.g. credentials.keys.MINIMAX_API_KEY")
    group.add_argument("--file", help="Dump a single memory file (e.g. openclaw)")
    group.add_argument("--search", help="Case-insensitive search across all files")
    group.add_argument("--ask", help="Deprecated compatibility flag; returns rc=2 and does not dispatch")
    group.add_argument("--status", action="store_true", help="Show memory DB status")
    group.add_argument("--backlinks", help="List incoming links to <slug> (memory-relative path or entity:ns:val)")
    group.add_argument("--graph", help="BFS from <slug> through typed-link graph (use --depth for hops)")

    p.add_argument("--section", help="With --file: dotted sub-path to extract")
    p.add_argument("--profile", help="Deprecated compatibility flag for --ask; ignored")
    p.add_argument("--timeout", type=float, default=60.0, help="Deprecated compatibility flag for --ask; ignored")
    p.add_argument("--files", help="With --search: comma-separated file names to restrict scope")
    p.add_argument("--depth", type=int, default=1, help="With --graph: BFS depth (default 1)")

    # ── v3 new-layout filters (usable standalone or with --search) ─────────
    p.add_argument(
        "--project",
        help="Project name (or '_shared') for structured fact listing",
    )
    p.add_argument(
        "--kind",
        help=(
            "Fact kind filter. M1: decision, delivery, issue, finding, reflection, "
            "library_knowledge, example, pattern, event. "
            "M2 (scanner): runtime, tests, deploy, ci, lint, structure, env_templates, dev_env."
        ),
    )
    p.add_argument(
        "--since",
        help="ISO-8601 date prefix filter on fact ts, e.g. '2026-04-01'",
    )

    return p.parse_args()


def main() -> int:
    args = parse_args()
    memory_dir = Path(args.memory_dir).expanduser().resolve()

    # ── v3 new-layout list mode (project / kind / since) ───────────────────
    # Activated when any of the v3 filters is given AND no v1 exclusive mode.
    _v3_triggered = bool(args.project or args.kind or args.since)
    _v1_mode = bool(
        args.key
        or args.file
        or args.search
        or args.ask
        or args.status
        or args.backlinks
        or args.graph
    )

    if _v3_triggered and not _v1_mode:
        return cmd_list(
            memory_dir,
            project=args.project,
            kind=args.kind,
            since=args.since,
        )

    # ── v1 backward-compatible modes ───────────────────────────────────────
    if args.status:
        return cmd_status(memory_dir)
    if args.key:
        return cmd_key(memory_dir, args.key)
    if args.file:
        return cmd_file(memory_dir, args.file, args.section)
    if args.search:
        files = args.files.split(",") if args.files else None
        return cmd_search(memory_dir, args.search, files=files)
    if args.backlinks:
        return cmd_backlinks(memory_dir, args.backlinks)
    if args.graph:
        return cmd_graph(memory_dir, args.graph, args.depth)
    if args.ask:
        return cmd_ask(args.ask, profile_path=args.profile, timeout=args.timeout)

    # Nothing given
    import argparse as _ap
    _ap.ArgumentParser(description=__doc__).print_help()
    print(
        "\nerror: specify one of: --key, --file, --search, --backlinks, "
        "--graph, --ask, --status, or --project/--kind/--since for v3 list mode",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
