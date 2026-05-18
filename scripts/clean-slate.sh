#!/usr/bin/env bash
# clean-slate.sh — reset the machine to a pre-ClawSeat-install state.
#
# Use cases:
#   - Simulate a fresh-machine install test (re-run the canonical install
#     from git clone without prior-install residue interfering).
#   - Uninstall ClawSeat on a machine where you no longer want it.
#   - CI smoke harness: guarantee clean baseline before a scripted install.
#
# Default behaviour is DRY-RUN: the script only prints what it would touch.
# Pass --yes to actually delete.
#
# WHAT IT DELETES
#   /tmp/ClawSeat                        — prior ancestor clone
#   ~/.openclaw/skills/{clawseat*,gstack-harness,lark-im,lark-shared,
#                       tmux-basics,clawseat-intake,cs}
#                                         — ClawSeat P0 skill symlinks
#   ~/.openclaw/workspace-*/skills/{clawseat*,gstack-harness,lark-im,
#                                   lark-shared,tmux-basics,
#                                   clawseat-intake}
#                                         — ClawSeat P3 overlay symlinks
#   ~/.claude/skills/{clawseat,clawseat-install,cs}
#   ~/.codex/skills/{clawseat,clawseat-install,cs}
#                                         — entry-skill symlinks (P4)
#   ~/.agents/                            — memory / sessions / tasks /
#                                           projects / profiles (full wipe)
#   Sandbox residue under:
#     ~/.agent-runtime/identities/<tool>/<auth>/<id>/home/{.openclaw,
#                                                          .claude,.agents}
#   Tmux sessions matching the canonical roster:
#     install-*, hardening-*, <project>-{memory,koder,planner,
#       builder-*,reviewer-*,patrol-*,designer-*}-claude
#
# WHAT IT PRESERVES (explicitly)
#   ~/.clawseat                           — developer source (if present)
#   ~/.gstack                             — gstack CLI install
#   ~/.lark-cli                           — user OAuth token
#   ~/.openclaw/{agents,openclaw.json,openclaw.json.bak.*,memory/*.sqlite
#                except mor.sqlite+koder.sqlite if --drop-seat-db}
#                                         — OpenClaw account state
#   ~/.agent-runtime/secrets/             — API keys (minimax, xcode-best…)
#   ~/.agent-runtime/identities/<t>/<a>/<i>/{home,xdg} directory skeletons
#     (contents cleaned above; dirs kept so ancestor launchers succeed)
#
# Usage
#   bash scripts/clean-slate.sh               # dry-run (default)
#   bash scripts/clean-slate.sh --yes         # commit to deletion
#   bash scripts/clean-slate.sh --yes --quiet # no per-path log
#   bash scripts/clean-slate.sh --drop-seat-db --yes
#                                              # also drop ~/.openclaw/memory/{mor,koder}.sqlite

set -u

DRY_RUN=1
QUIET=0
DROP_SEAT_DB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) DRY_RUN=0 ;;
    --quiet|-q) QUIET=1 ;;
    --drop-seat-db) DROP_SEAT_DB=1 ;;
    --help|-h)
      sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

HOME_DIR="${HOME:-/Users/$USER}"
CLAWSEAT_SKILLS=(
  clawseat clawseat-install
  gstack-harness lark-im lark-shared
  tmux-basics clawseat-intake cs
)
CLAWSEAT_OVERLAY_SKILLS=(
  clawseat clawseat-install
  gstack-harness lark-im lark-shared
  tmux-basics clawseat-intake
)
CLAWSEAT_ENTRY_SKILLS=( clawseat clawseat-install cs )

DELETED=0
KEPT=0

log() { [[ $QUIET -eq 1 ]] || echo "$@"; }

rm_path() {
  local p="$1"
  if [[ ! -e "$p" && ! -L "$p" ]]; then
    return 0
  fi
  if [[ $DRY_RUN -eq 1 ]]; then
    log "would_delete: $p"
  else
    rm -rf -- "$p"
    log "deleted:      $p"
  fi
  DELETED=$((DELETED + 1))
}

preserve() {
  local p="$1"
  [[ -e "$p" || -L "$p" ]] || return 0
  log "preserved:    $p"
  KEPT=$((KEPT + 1))
}

kill_tmux_sessions() {
  if ! command -v tmux >/dev/null 2>&1; then
    return 0
  fi
  if ! tmux ls 2>/dev/null | grep -q .; then
    log "tmux:         no server running"
    return 0
  fi
  local pattern='^(install-|hardening-|[a-z0-9_-]+-(memory|koder|planner|builder-[0-9]+|reviewer-[0-9]+|patrol-[0-9]+|designer-[0-9]+)-claude)'
  local sessions
  sessions=$(tmux ls -F '#{session_name}' 2>/dev/null | grep -E "$pattern" || true)
  if [[ -z "$sessions" ]]; then
    log "tmux:         no matching sessions"
    return 0
  fi
  while IFS= read -r s; do
    [[ -z "$s" ]] && continue
    if [[ $DRY_RUN -eq 1 ]]; then
      log "would_kill_tmux: $s"
    else
      tmux kill-session -t "$s" 2>/dev/null || true
      log "killed_tmux:     $s"
    fi
    DELETED=$((DELETED + 1))
  done <<< "$sessions"
}

header() {
  [[ $QUIET -eq 1 ]] && return
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "=== clean-slate.sh — DRY RUN (pass --yes to delete) ==="
  else
    echo "=== clean-slate.sh — DELETING ==="
  fi
}

footer() {
  [[ $QUIET -eq 1 ]] && return
  echo "==="
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "dry-run summary: $DELETED path(s)/session(s) would be deleted; $KEPT preserved"
    echo "re-run with --yes to actually clean."
  else
    echo "cleanup summary: $DELETED path(s)/session(s) deleted; $KEPT preserved."
    echo "machine is now in pre-ClawSeat-install state. Ready for:"
    echo "  git clone https://github.com/KaneOrca/ClawSeat.git /tmp/ClawSeat"
    echo "  export CLAWSEAT_ROOT=/tmp/ClawSeat"
    echo "  # follow README install flow (6-phase canonical)"
  fi
}

header

# ── Prior clone ─────────────────────────────────────────────────────────
rm_path "/tmp/ClawSeat"

# ── P0 shared skill symlinks ────────────────────────────────────────────
if [[ -d "$HOME_DIR/.openclaw/skills" ]]; then
  for s in "${CLAWSEAT_SKILLS[@]}"; do
    rm_path "$HOME_DIR/.openclaw/skills/$s"
  done
fi

# ── P3 per-agent overlay symlinks ───────────────────────────────────────
if [[ -d "$HOME_DIR/.openclaw" ]]; then
  for ws in "$HOME_DIR"/.openclaw/workspace-*; do
    [[ -d "$ws" ]] || continue
    [[ "$(basename "$ws")" == "workspace-*" ]] && continue  # no matches
    for s in "${CLAWSEAT_OVERLAY_SKILLS[@]}"; do
      rm_path "$ws/skills/$s"
    done
  done
fi

# ── P4 entry-skill symlinks ─────────────────────────────────────────────
for root in "$HOME_DIR/.claude/skills" "$HOME_DIR/.codex/skills"; do
  [[ -d "$root" ]] || continue
  for s in "${CLAWSEAT_ENTRY_SKILLS[@]}"; do
    rm_path "$root/$s"
  done
done

# ── ~/.agents/ (memory + sessions + tasks + projects + profiles) ────────
rm_path "$HOME_DIR/.agents"

# ── Sandbox residue under ~/.agent-runtime/identities/*/*/*/home/ ───────
if [[ -d "$HOME_DIR/.agent-runtime/identities" ]]; then
  # Depth-3 iteration: tool/auth/identity
  while IFS= read -r -d '' home_dir; do
    for sub in .openclaw .claude .agents; do
      rm_path "$home_dir/$sub"
    done
  done < <(find "$HOME_DIR/.agent-runtime/identities" \
             -mindepth 4 -maxdepth 4 -type d -name home -print0 2>/dev/null)
fi

# ── Optional: drop seat-specific OpenClaw sqlite databases ──────────────
if [[ $DROP_SEAT_DB -eq 1 && -d "$HOME_DIR/.openclaw/memory" ]]; then
  rm_path "$HOME_DIR/.openclaw/memory/mor.sqlite"
  rm_path "$HOME_DIR/.openclaw/memory/koder.sqlite"
fi

# ── Tmux sessions ───────────────────────────────────────────────────────
kill_tmux_sessions

# ── Preserve-list verification (informational) ──────────────────────────
if [[ $QUIET -eq 0 ]]; then
  echo "--- preserved (not touched) ---"
fi
preserve "$HOME_DIR/.clawseat"
preserve "$HOME_DIR/.gstack"
preserve "$HOME_DIR/.lark-cli"
preserve "$HOME_DIR/.openclaw/agents"
preserve "$HOME_DIR/.openclaw/openclaw.json"
preserve "$HOME_DIR/.agent-runtime/secrets"

footer
exit 0
