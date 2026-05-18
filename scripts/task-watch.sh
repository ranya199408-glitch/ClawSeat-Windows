#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${CLAWSEAT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROJECTS_DIR="${CLAWSEAT_PROJECTS_DIR:-${HOME}/.agents/tasks}"
OPS_DIR="$REPO_ROOT/.agent/ops/install-nonint"
OUT_DIR="$REPO_ROOT/.agent/task-watch"
REPORT="$OUT_DIR/latest.md"
INSTALL_SESSION="install-runner"
timestamp="$(date '+%Y-%m-%d %H:%M:%S %Z')"
TMUX_BIN="$(command -v tmux 2>/dev/null || true)"
if [[ -z "$TMUX_BIN" ]]; then
  for candidate in /opt/homebrew/bin/tmux /usr/local/bin/tmux /usr/bin/tmux; do
    if [[ -x "$candidate" ]]; then
      TMUX_BIN="$candidate"
      break
    fi
  done
fi
TMUX_BIN="${TMUX_BIN:-tmux}"

mkdir -p "$OUT_DIR"

python3 - "$PROJECTS_DIR" "$OPS_DIR" "$REPORT" "$timestamp" "$INSTALL_SESSION" "$TMUX_BIN" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

projects_dir = Path(sys.argv[1])
ops_dir = Path(sys.argv[2])
report = Path(sys.argv[3])
timestamp = sys.argv[4]
install_session = sys.argv[5]
tmux_bin = sys.argv[6]


def parse_project_tasks(project_md: Path) -> list[tuple[str, str, str]]:
    text = project_md.read_text(encoding="utf-8")
    tasks: list[tuple[str, str, str]] = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| # | Task | Status | Priority | Updated |"):
            in_table = True
            continue
        if in_table and not line.startswith("|"):
            break
        if not in_table or line.startswith("|---"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) != 5:
            continue
        if cols[0] == "#":
            continue
        status = cols[2]
        if status in {"todo", "blocked", "in_progress"}:
            tasks.append((cols[0], cols[1], status))
    return tasks


def parse_ops_todos(ops_dir: Path) -> list[tuple[str, str, str]]:
    todos: list[tuple[str, str, str]] = []
    for todo in sorted(ops_dir.glob("TODO-*.md")):
        text = todo.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^task_id:\s*([A-Z0-9-]+)\s*$", text, re.M)
        if not m:
            continue
        task_id = m.group(1)
        delivery = ops_dir / f"DELIVERY-{task_id}.md"
        if delivery.exists():
            continue
        title = todo.stem.replace("TODO-", "")
        todos.append((task_id, title, "todo"))
    return todos


def capture_tmux(session: str) -> str:
    import subprocess

    # Exact-match (-t "=<name>") prevents substring collision (audit §10.5).
    # Cannot import core.lib.tmux here; inline implementation is intentional.
    try:
        result = subprocess.run(
            [tmux_bin, "has-session", "-t", f"={session}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return "not running"
        pane = subprocess.run(
            [tmux_bin, "capture-pane", "-t", session, "-p"],
            capture_output=True,
            text=True,
            check=False,
        )
        if pane.returncode != 0:
            return "running, capture failed"
        return "running\\n" + "\\n".join(pane.stdout.splitlines()[-40:])
    except FileNotFoundError:
        return "tmux missing"


project_lines: list[str] = []
for project_md in sorted(projects_dir.glob("*/PROJECT.md")):
    project_name = project_md.parent.name
    tasks = parse_project_tasks(project_md)
    if not tasks:
        continue
    project_lines.append(f"### {project_name}")
    for task_no, title, status in tasks:
        project_lines.append(f"- {task_no} [{status}] {title}")

ops_lines = parse_ops_todos(ops_dir)

report_lines: list[str] = [
    "# Task Watch Report",
    f"- generated: {timestamp}",
    "",
    "## Active project tasks",
]
if project_lines:
    report_lines.extend(project_lines)
else:
    report_lines.append("- none")

report_lines.extend([
    "",
    "## Open install-nonint TODOs without delivery",
])
if ops_lines:
    for task_id, title, _ in ops_lines:
        report_lines.append(f"- {task_id}: {title}")
else:
    report_lines.append("- none")

report_lines.extend([
    "",
    f"## {install_session} snapshot",
    capture_tmux(install_session),
])

report.write_text("\\n".join(report_lines) + "\\n", encoding="utf-8")
print(report)
PY
