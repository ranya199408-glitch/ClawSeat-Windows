#!/usr/bin/env python3
"""modal_detector — detect Claude Code numbered-choice modals in tmux panes (C10.5).

Usage::

    modal_detector.py --once                        # Scan all live sessions once, exit.
    modal_detector.py --watch [--interval 60]       # Loop until SIGINT.
    modal_detector.py --dry-run                     # Print matches; no DB writes.
    modal_detector.py --project install             # Scope to one project.
    modal_detector.py --install-launchd [--interval 60]  # Write launchd plist, print load command.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.lib.state import _utcnow, open_db, record_event_if_new  # noqa: E402

# ---------------------------------------------------------------------------
# Modal pattern
# ---------------------------------------------------------------------------

# Matches "Do you want to proceed?" (or similar CC prompts) followed by
# 2+ numbered options (optionally prefixed with ❯).
MODAL_PATTERN = re.compile(
    r"(Do you want to proceed\?[^\n]*)\n"
    r"((?:[^\n]*?(?:❯\s*)?\d+\.[^\n]+\n){2,})",
    re.DOTALL,
)

# Fallback pattern: any numbered list with 2+ options after a question-like line
_NUMBERED_BLOCK_PATTERN = re.compile(
    r"([^\n?]+\?[^\n]*)\n"
    r"((?:[^\n]*?(?:❯\s*)?\d+\.[^\n]+\n){2,})",
    re.DOTALL,
)


@dataclass
class ModalMatch:
    question: str
    options: list[str]
    preview: str


def _detect_modal(pane_text: str) -> ModalMatch | None:
    """Return a ModalMatch if the pane text contains a CC numbered-choice modal."""
    tail = pane_text[-3000:]
    m = MODAL_PATTERN.search(tail)
    if not m:
        return None
    options = [
        line.strip().lstrip("❯ ").strip()
        for line in m.group(2).splitlines()
        if line.strip()
    ]
    if len(options) < 2:
        return None
    preview = tail[max(0, m.start() - 200): m.end() + 50].strip()
    return ModalMatch(
        question=m.group(1).strip(),
        options=options,
        preview=preview,
    )


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def _fingerprint(session: str, question: str, options: list[str]) -> str:
    seed = f"{session}:{question}:{'|'.join(options)}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _list_live_sessions(tmux_bin: str = "tmux") -> list[str]:
    """Return names of all live tmux sessions."""
    try:
        out = subprocess.check_output(
            [tmux_bin, "list-sessions", "-F", "#{session_name}"],
            text=True,
            env={**os.environ, "TMUX": ""},
            stderr=subprocess.DEVNULL,
        )
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def _capture_pane(session: str, tmux_bin: str = "tmux") -> str:
    """Return the last 120 lines of the given tmux session's pane."""
    try:
        return subprocess.check_output(
            [tmux_bin, "capture-pane", "-t", session, "-p", "-S", "-120"],
            text=True,
            env={**os.environ, "TMUX": ""},
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _parse_session_name(session: str) -> tuple[str, str]:
    """Parse tmux session name into (project, seat).

    Examples:
      install-builder-2-claude  → (install, builder-2)
      myproject-planner-claude  → (myproject, planner)
      ancestor-cc               → (ancestor, cc)
    """
    # Strip known tool suffixes (-claude, -codex, -cc) only when enough
    # parts remain so we don't consume the seat name.
    name = session
    for suffix in ("-claude", "-codex", "-cc"):
        if name.endswith(suffix):
            candidate = name[: -len(suffix)]
            if "-" in candidate:  # still has project-seat structure
                name = candidate
            break
    parts = name.split("-", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return name, name


# ---------------------------------------------------------------------------
# Core scan
# ---------------------------------------------------------------------------


def scan_once(
    *,
    project_filter: str | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
    tmux_bin: str = "tmux",
) -> dict[str, int]:
    """Scan all live tmux sessions for CC modals. Return stats."""
    stats: dict[str, int] = {"sessions": 0, "modals": 0, "inserted": 0, "skipped": 0}
    sessions = _list_live_sessions(tmux_bin)
    for session in sessions:
        if project_filter and not session.startswith(f"{project_filter}-"):
            continue
        stats["sessions"] += 1
        pane = _capture_pane(session, tmux_bin)
        modal = _detect_modal(pane)
        if modal is None:
            continue
        stats["modals"] += 1
        project, seat = _parse_session_name(session)
        fp = _fingerprint(session, modal.question, modal.options)
        if dry_run:
            print(
                f"[DRY-RUN] session={session} project={project} seat={seat}\n"
                f"  question: {modal.question}\n"
                f"  options: {modal.options}\n"
                f"  fingerprint: {fp}"
            )
            stats["inserted"] += 1
            continue
        with open_db(db_path) as conn:
            inserted = record_event_if_new(
                conn,
                "seat.blocked_on_modal",
                project,
                fingerprint=fp,
                seat=seat,
                session=session,
                question=modal.question[:200],
                options=modal.options,
                detected_at=_utcnow(),
            )
        if inserted:
            stats["inserted"] += 1
            print(f"modal_event: {session} ({project}/{seat}) fingerprint={fp}")
        else:
            stats["skipped"] += 1
    return stats


# ---------------------------------------------------------------------------
# Watch loop
# ---------------------------------------------------------------------------


def run_watch(
    *,
    interval: int,
    project_filter: str | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
    tmux_bin: str = "tmux",
) -> int:
    _stop = [False]

    def _handle_sigint(sig: int, frame: Any) -> None:
        _stop[0] = True

    signal.signal(signal.SIGINT, _handle_sigint)
    cycles = 0
    while not _stop[0]:
        cycles += 1
        stats = scan_once(
            project_filter=project_filter,
            dry_run=dry_run,
            db_path=db_path,
            tmux_bin=tmux_bin,
        )
        print(
            f"cycle={cycles} sessions={stats['sessions']} modals={stats['modals']} "
            f"inserted={stats['inserted']} skipped={stats['skipped']}"
        )
        for _ in range(interval):
            if _stop[0]:
                break
            time.sleep(1)
    return 0


# ---------------------------------------------------------------------------
# launchd plist install
# ---------------------------------------------------------------------------


_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.clawseat.modal-detector</string>
  <key>ProgramArguments</key>
  <array>
    <string>{PYTHON_BIN}</string>
    <string>{CLAWSEAT_ROOT}/core/scripts/modal_detector.py</string>
    <string>--watch</string>
    <string>--interval</string>
    <string>{interval}</string>
  </array>
  <key>StartInterval</key><integer>{interval}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{HOME}/.agents/logs/modal-detector.log</string>
  <key>StandardErrorPath</key><string>{HOME}/.agents/logs/modal-detector.err</string>
</dict>
</plist>
"""

_LAUNCHD_DEST = Path.home() / "Library" / "LaunchAgents" / "com.clawseat.modal-detector.plist"


def render_plist(interval: int, python_bin: str | None = None) -> str:
    return _PLIST_TEMPLATE.format(
        PYTHON_BIN=python_bin or sys.executable,
        CLAWSEAT_ROOT=str(_REPO_ROOT),
        interval=interval,
        HOME=str(Path.home()),
    )


def install_launchd(interval: int, dest: Path | None = None) -> int:
    out_path = dest or _LAUNCHD_DEST
    xml = render_plist(interval)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(xml, encoding="utf-8")
    print(f"installed: {out_path}")
    print(f"Run: launchctl load {out_path}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="modal_detector",
        description="Detect CC numbered-choice modals in tmux panes and emit seat.blocked_on_modal events.",
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Scan once and exit.")
    mode.add_argument("--watch", action="store_true", help="Loop until SIGINT.")
    mode.add_argument("--install-launchd", action="store_true", help="Write launchd plist and exit.")

    p.add_argument("--interval", type=int, default=60, help="Watch interval in seconds (default 60).")
    p.add_argument("--dry-run", action="store_true", help="Print matches without DB writes.")
    p.add_argument("--project", default=None, help="Scope to one project prefix.")
    p.add_argument("--db", default=None, dest="db_path", help="Override state.db path.")
    p.add_argument("--tmux-bin", default="tmux", help="Path to tmux binary.")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.install_launchd:
        return install_launchd(args.interval)

    if args.once:
        stats = scan_once(
            project_filter=args.project,
            dry_run=args.dry_run,
            db_path=args.db_path,
            tmux_bin=args.tmux_bin,
        )
        print(
            f"sessions={stats['sessions']} modals={stats['modals']} "
            f"inserted={stats['inserted']} skipped={stats['skipped']}"
        )
        return 0

    # --watch
    return run_watch(
        interval=args.interval,
        project_filter=args.project,
        dry_run=args.dry_run,
        db_path=args.db_path,
        tmux_bin=args.tmux_bin,
    )


if __name__ == "__main__":
    sys.exit(main())
