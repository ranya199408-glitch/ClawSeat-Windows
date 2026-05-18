#!/usr/bin/env bash
set -euo pipefail

PROJECT="clawseat"
CLAWSEAT_ROOT="$HOME/ClawSeat"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --clawseat-root) CLAWSEAT_ROOT="$2"; shift 2 ;;
    --help)
      echo "Usage: scripts/launch-grid.sh [--project <name>] [--clawseat-root <path>]"
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

CLAWSEAT_ROOT="${CLAWSEAT_ROOT/#\~/$HOME}"
read_project_seats() {
  python3 - "$PROJECT" <<'PY'
from pathlib import Path
import sys
import tomllib

project = sys.argv[1]
fallback = ["memory", "planner", "builder", "reviewer", "patrol", "designer"]
project_toml = Path.home() / ".agents" / "projects" / project / "project.toml"
try:
    with project_toml.open("rb") as fh:
        data = tomllib.load(fh)
except Exception:
    print("\n".join(fallback))
    raise SystemExit(0)

engineers = data.get("engineers")
if not isinstance(engineers, list) or not engineers:
    print("\n".join(fallback))
    raise SystemExit(0)

cleaned = [str(seat).strip() for seat in engineers if str(seat).strip()]
print("\n".join(cleaned or fallback))
PY
}

SEATS=()
while IFS= read -r seat; do
  [[ -n "$seat" ]] && SEATS+=("$seat")
done < <(read_project_seats)
if [[ "${#SEATS[@]}" -eq 0 ]]; then
  SEATS=(memory planner builder reviewer patrol designer)
fi
PRIMARY_SEAT_ID="${SEATS[0]}"
SEATS_CSV="$(IFS=,; printf '%s' "${SEATS[*]}")"

ensure_session() {
  local name="$1" cmd="$2"
  tmux has-session -t "$name" 2>/dev/null && return 0
  tmux new-session -d -s "$name" -c "$CLAWSEAT_ROOT" "$cmd"
}

ensure_session "${PROJECT}-${PRIMARY_SEAT_ID}" "bash -lc 'claude --dangerously-skip-permissions; exec bash'"
for seat in "${SEATS[@]:1}"; do
  ensure_session "${PROJECT}-${seat}" "bash"
done

PROJECT="$PROJECT" CLAWSEAT_ROOT="$CLAWSEAT_ROOT" SEATS_CSV="$SEATS_CSV" python3 - <<'PY'
import os
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(os.environ["CLAWSEAT_ROOT"]).expanduser()
sys.path.insert(0, str(root / "core" / "scripts"))
from agent_admin_window import build_monitor_layout

seats = [seat for seat in os.environ["SEATS_CSV"].split(",") if seat]
project = SimpleNamespace(
    name=os.environ["PROJECT"],
    repo_root=str(root),
    monitor_session=f"{os.environ['PROJECT']}-monitor",
    monitor_engineers=seats,
    monitor_max_panes=len(seats),
    window_mode="grid-6up",
)
sessions = {
    seat: SimpleNamespace(engineer_id=seat, session=f"{os.environ['PROJECT']}-{seat}")
    for seat in seats
}
build_monitor_layout(project, sessions)
PY

echo "tmux attach -t ${PROJECT}-monitor"
