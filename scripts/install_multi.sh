#!/usr/bin/env bash
# ClawSeat v3 multi-team minimal install (Phase 1).
#
# Renders v3 project.toml from approved config proposals + creates
# workspace skeleton. This is the Phase 1 minimal path; full install.sh
# integration with --mode multi flag is Phase 4.
#
# Usage:
#   bash scripts/install_multi.sh --project <name> [--repo-root <path>]
#
# Prerequisites:
#   tasks/<project>/_config-proposals/<team>__approved.yaml for each team
#
# Spec ref: §4.1, §9, §16.7 in clawseat-v3-multi-team-protocol.md
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROJECT=""
REPO_ROOT_OVERRIDE=""
TEAMS_FILTER=""
DRY_RUN=0
UPGRADE_TEAM=""

usage() {
  cat <<EOF
Usage: $0 --project <name> [--teams <csv>] [--repo-root <path>] [--dry-run]
       $0 --project <name> --upgrade-team <team> [--dry-run]

Render v3 project.toml from approved config proposals.
Prerequisite: \$HOME/.agents/tasks/<project>/_config-proposals/<team>__approved.yaml exists.

Flags:
  --teams <csv>       Optional comma-separated filter (default: all approved teams).
                      Unknown team names hard-fail.
  --upgrade-team <t>  Incremental: re-render project.toml to include team <t>
                      while preserving existing teams. Requires the new team's
                      __approved.yaml to be present. Existing teams discovered
                      from existing tasks/<project>/<team>/ dirs.

EOF
  exit "${1:-0}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2 ;;
    --teams) TEAMS_FILTER="$2"; shift 2 ;;
    --upgrade-team) UPGRADE_TEAM="$2"; shift 2 ;;
    --repo-root) REPO_ROOT_OVERRIDE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --help|-h) usage 0 ;;
    *) echo "unknown arg: $1" >&2; usage 1 ;;
  esac
done

if [ -z "$PROJECT" ]; then
  echo "--project required" >&2
  usage 1
fi

REAL_HOME="${CLAWSEAT_REAL_HOME:-$HOME}"
AGENTS_ROOT="$REAL_HOME/.agents"
PROPOSALS_DIR="$AGENTS_ROOT/tasks/$PROJECT/_config-proposals"

# --upgrade-team: derive --teams from existing team dirs + new team
if [ -n "$UPGRADE_TEAM" ]; then
  if [ -n "$TEAMS_FILTER" ]; then
    echo "--upgrade-team and --teams are mutually exclusive" >&2
    exit 2
  fi
  if [ ! -f "$PROPOSALS_DIR/${UPGRADE_TEAM}__approved.yaml" ]; then
    echo "approved config for new team '$UPGRADE_TEAM' missing: $PROPOSALS_DIR/${UPGRADE_TEAM}__approved.yaml" >&2
    exit 2
  fi
  existing_teams=""
  if [ -d "$AGENTS_ROOT/tasks/$PROJECT" ]; then
    for d in "$AGENTS_ROOT/tasks/$PROJECT"/*/; do
      [ -d "$d" ] || continue
      tname="$(basename "$d")"
      [ "$tname" = "_config-proposals" ] && continue
      [ "$tname" = "contracts" ] && continue
      [ -f "$d/tasks.queue.jsonl" ] || [ -d "$d/brief" ] || continue
      existing_teams="${existing_teams:+$existing_teams,}$tname"
    done
  fi
  if echo ",$existing_teams," | grep -q ",$UPGRADE_TEAM,"; then
    TEAMS_FILTER="$existing_teams"
  else
    TEAMS_FILTER="${existing_teams:+$existing_teams,}$UPGRADE_TEAM"
  fi
  echo "→ upgrade-team: rendering teams=$TEAMS_FILTER"
fi
PROFILE_OUT="$AGENTS_ROOT/profiles/${PROJECT}-profile-dynamic.toml"
RENDER_SCRIPT="$REPO_ROOT/core/scripts/render_project_toml_v3.py"
VALIDATOR="$REPO_ROOT/core/lib/proposal_validator.py"

# Step 1: proposals dir must exist + have at least 1 approved yaml
if [ ! -d "$PROPOSALS_DIR" ]; then
  echo "proposals dir missing: $PROPOSALS_DIR" >&2
  echo "Memory must first write per-team config proposals (§16) and operator approves." >&2
  exit 2
fi

approved_count=0
for f in "$PROPOSALS_DIR"/*__approved.yaml; do
  [ -f "$f" ] && approved_count=$((approved_count + 1))
done
if [ "$approved_count" -eq 0 ]; then
  echo "no *__approved.yaml in $PROPOSALS_DIR" >&2
  exit 2
fi

# Step 2: validate proposals (§16.7 render validation)
echo "→ validating $approved_count approved config(s) in $PROPOSALS_DIR"
if ! "$PYTHON_BIN" "$VALIDATOR" "$PROPOSALS_DIR"; then
  echo "validation failed; refusing to render" >&2
  exit 3
fi

# Step 3: render project.toml (with optional --teams filter)
echo "→ rendering project.toml${TEAMS_FILTER:+ (teams=$TEAMS_FILTER)}"
if [ "$DRY_RUN" -eq 1 ]; then
  "$PYTHON_BIN" "$RENDER_SCRIPT" \
    --project "$PROJECT" \
    --proposals-dir "$PROPOSALS_DIR" \
    ${REPO_ROOT_OVERRIDE:+--repo-root "$REPO_ROOT_OVERRIDE"} \
    ${TEAMS_FILTER:+--teams "$TEAMS_FILTER"} \
    --output -
  echo "→ dry-run; not writing"
  exit 0
fi

mkdir -p "$(dirname "$PROFILE_OUT")"
"$PYTHON_BIN" "$RENDER_SCRIPT" \
  --project "$PROJECT" \
  --proposals-dir "$PROPOSALS_DIR" \
  ${REPO_ROOT_OVERRIDE:+--repo-root "$REPO_ROOT_OVERRIDE"} \
  ${TEAMS_FILTER:+--teams "$TEAMS_FILTER"} \
  --output "$PROFILE_OUT"

# Step 4: workspace skeleton dirs (only for teams included in render)
echo "→ creating workspace skeleton"
if [ -n "$TEAMS_FILTER" ]; then
  # Skeleton only for explicitly requested teams
  IFS=',' read -ra _TEAM_LIST <<< "$TEAMS_FILTER"
  for team in "${_TEAM_LIST[@]}"; do
    team="$(echo "$team" | tr -d '[:space:]')"
    team_dir="$AGENTS_ROOT/tasks/$PROJECT/$team"
    mkdir -p "$team_dir/brief" "$team_dir/workflow" "$team_dir/DELIVERY" "$team_dir/acceptance"
    : > "$team_dir/tasks.queue.jsonl.placeholder"
  done
else
  for f in "$PROPOSALS_DIR"/*__approved.yaml; do
    team="$(basename "$f" __approved.yaml)"
    team_dir="$AGENTS_ROOT/tasks/$PROJECT/$team"
    mkdir -p "$team_dir/brief" "$team_dir/workflow" "$team_dir/DELIVERY" "$team_dir/acceptance"
    : > "$team_dir/tasks.queue.jsonl.placeholder"
  done
fi

# Step 5: contracts dir (cross-team)
mkdir -p "$AGENTS_ROOT/tasks/$PROJECT/contracts"

# Step 6: verify with v3 loader (round-trip sanity)
echo "→ verifying with v3 loader"
"$PYTHON_BIN" - <<EOF
import sys
sys.path.insert(0, "$REPO_ROOT/core/lib")
from profile_loader_v3 import load_profile_v3
p = load_profile_v3("$PROFILE_OUT")
print(f"  project: {p.project_name}")
print(f"  mode: {p.team_structure}")
print(f"  teams: {sorted(p.teams.keys())}")
print(f"  total seats: {len(p.seats)}")
EOF

echo ""
echo "v3 multi-mode render complete:"
echo "  profile: $PROFILE_OUT"
echo "  workspace: $AGENTS_ROOT/tasks/$PROJECT/"
