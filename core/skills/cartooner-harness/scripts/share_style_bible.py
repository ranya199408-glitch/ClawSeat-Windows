#!/usr/bin/env python3
"""share_style_bible.py — Set / get the project's style_bible pointer.

Style bible is one of the L1 anchors (alongside brief.md and vision_spec.md)
that builder-image / builder-av reference when spawning lanes. This script
is the only sanctioned way to update the project-level pointer; lanes that
need style coherence read PROJECT_INDEX.style_bible.

Effect (--action set)
---------------------
- Validates --bible-path exists + is readable (path stat only; never reads
  bible content into this script — caller seats that need content read
  the file themselves)
- Increments PROJECT_INDEX.style_bible.version
- Updates PROJECT_INDEX.style_bible {path, version, set_by, set_at, note}
- Appends generation_log (event=share_style_bible)
- Prints the new version number to stdout

Effect (--action get)
---------------------
- Prints current style_bible.path to stdout (empty if unset)
- Exits 0 even when unset (caller decides whether unset is fatal)

Effect (--action history)
-------------------------
- Prints PROJECT_INDEX.style_bible.history as JSONL to stdout (one record
  per line; latest first)

character_dna.json follows a parallel pattern via --target character-dna.

Exit
----
- 0 on success
- non-zero on validation failure (fail-closed)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common as common  # noqa: E402

VALID_ACTIONS = ("set", "get", "history")
VALID_TARGETS = ("style-bible", "character-dna")
VALID_ACTORS = ("user", "memory_acting_director")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="share_style_bible")
    p.add_argument("--project", required=True)
    p.add_argument("--action", required=True, choices=VALID_ACTIONS)
    p.add_argument("--target", default="style-bible", choices=VALID_TARGETS,
                   help="Which artifact pointer (style_bible | character_dna)")
    p.add_argument("--bible-path", default="",
                   help="(set) absolute path to the artifact file")
    p.add_argument("--actor", default="user", choices=VALID_ACTORS)
    p.add_argument("--note", default="",
                   help="(set) free-form note describing the version (e.g. 'darker palette pass')")
    return p.parse_args(argv)


def index_key(target: str) -> str:
    return "style_bible" if target == "style-bible" else "character_dna"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    common.ensure_project_skeleton(args.project)
    index = common.load_project_index(args.project)
    key = index_key(args.target)

    if args.action == "get":
        record = index.get(key) or {}
        print(record.get("path", ""))
        return 0

    if args.action == "history":
        record = index.get(key) or {}
        history = record.get("history") or []
        for entry in history:
            sys.stdout.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return 0

    if not args.bible_path:
        common.fail_closed(f"--action set requires --bible-path")

    target_path = Path(args.bible_path).expanduser()
    if not target_path.exists():
        common.fail_closed(f"--bible-path does not exist: {target_path}")
    if not target_path.is_file():
        common.fail_closed(f"--bible-path is not a regular file: {target_path}")

    now = common.now_iso()
    existing = index.get(key) or {}
    next_version = int(existing.get("version", 0)) + 1

    history = list(existing.get("history") or [])
    if existing.get("path"):
        history.append({
            "version": existing.get("version", 0),
            "path": existing.get("path"),
            "set_by": existing.get("set_by"),
            "set_at": existing.get("set_at"),
            "note": existing.get("note"),
        })

    record = {
        "path": str(target_path),
        "version": next_version,
        "set_by": args.actor,
        "set_at": now,
        "note": args.note,
        "history": history,
    }
    index[key] = record

    common.write_project_index(args.project, index)

    common.append_generation_log(args.project, {
        "event": "share_style_bible",
        "target": args.target,
        "path": str(target_path),
        "version": next_version,
        "actor": args.actor,
        "note": args.note or None,
    })

    print(next_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
