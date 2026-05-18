#!/usr/bin/env bash
# shellcheck shell=bash
# EE3: Intelligent environment detection for AI-native install UX.

_CLAWSEAT_DETECT_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

_detect_repo_root() {
  if [[ -n "${CLAWSEAT_ROOT:-}" ]]; then
    printf '%s\n' "$CLAWSEAT_ROOT"
  else
    cd "$_CLAWSEAT_DETECT_LIB_DIR/../../.." && pwd
  fi
}

_detect_legacy_oauth_file() {
  local -a candidates=("$@")
  local candidate=""
  for candidate in "${candidates[@]}"; do
    [[ -s "$candidate" ]] && { printf 'oauth\n'; return 0; }
  done
  printf 'missing\n'
}

_detect_claude_state() {
  # Claude Code v2.x on macOS stores OAuth credentials in Keychain.
  if [[ "${CLAWSEAT_TEST_OSTYPE:-$OSTYPE}" == darwin* ]]; then
    if security find-generic-password -s "Claude Code-credentials" -w >/dev/null 2>&1; then
      printf 'oauth\n'
      return 0
    fi
  fi

  # Claude Code also keeps account metadata in ~/.claude.json.
  if [[ -f "$HOME/.claude.json" ]]; then
    if python3 - "$HOME/.claude.json" <<'PY' 2>/dev/null; then
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if "oauthAccount" in data else 1)
PY
      printf 'oauth\n'
      return 0
    fi
    if grep -q '"oauthAccount"' "$HOME/.claude.json" 2>/dev/null; then
      printf 'oauth\n'
      return 0
    fi
  fi

  if [[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    printf 'oauth\n'
    return 0
  fi

  if [[ -n "${ANTHROPIC_API_KEY:-}" || -n "${CLAUDE_API_KEY:-}" ]]; then
    printf 'api_key\n'
    return 0
  fi

  _detect_legacy_oauth_file \
    "$HOME/.claude/auth.json" \
    "$HOME/.claude/.credentials.json" \
    "$HOME/.config/claude/auth.json"
}

_detect_codex_state() {
  if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    printf 'api_key\n'
    return 0
  fi

  _detect_legacy_oauth_file \
    "$HOME/.codex/auth.json" \
    "$HOME/.codex/auth.toml" \
    "$HOME/.codex/auth"
}

_detect_gemini_state() {
  if [[ -n "${GEMINI_API_KEY:-}" || -n "${GOOGLE_API_KEY:-}" ]]; then
    printf 'api_key\n'
    return 0
  fi

  _detect_legacy_oauth_file \
    "$HOME/.gemini/oauth_creds.json" \
    "$HOME/.gemini/auth.json" \
    "$HOME/.config/gcloud/application_default_credentials.json"
}

detect_oauth_states() {
  local claude_state="missing" codex_state="missing" gemini_state="missing"

  claude_state="$(_detect_claude_state)"
  codex_state="$(_detect_codex_state)"
  gemini_state="$(_detect_gemini_state)"

  printf '{"claude":"%s","codex":"%s","gemini":"%s"}\n' \
    "$claude_state" "$codex_state" "$gemini_state"
}

detect_pty_resource() {
  local used="0" total="256" warn="false"
  used="$(tmux ls 2>/dev/null | wc -l | tr -d '[:space:]' 2>/dev/null || true)"
  [[ "$used" =~ ^[0-9]+$ ]] || used="0"
  (( used > 200 )) && warn="true"
  printf '{"used":%s,"total":%s,"warn":%s}\n' "$used" "$total" "$warn"
}

detect_template_from_name() {
  local name="${1:-}" lowered=""
  lowered="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]')"
  if [[ "$lowered" =~ (solo|minimal|personal) ]]; then
    printf 'clawseat-solo\n'
  elif [[ "$lowered" =~ (game|app|api|server|backend|web|tool) ]]; then
    printf 'clawseat-engineering\n'
  else
    printf 'clawseat-creative\n'
  fi
}

detect_branch_state() {
  local repo_root="" branch="" warn="false"
  repo_root="$(_detect_repo_root)"
  branch="$(git -C "$repo_root" rev-parse --abbrev-ref HEAD 2>/dev/null || printf 'unknown')"
  [[ "$branch" != "main" ]] && warn="true"
  python3 - "$branch" "$warn" <<'PY'
import json
import sys

branch = sys.argv[1]
warn = sys.argv[2] == "true"
print(json.dumps({"branch": branch, "warn": warn}))
PY
}

detect_existing_projects() {
  local dir="$HOME/.agents/projects"
  if [[ ! -d "$dir" ]]; then
    printf '[]\n'
    return 0
  fi
  find "$dir" -maxdepth 1 -mindepth 1 -type d -print 2>/dev/null \
    | sort \
    | while IFS= read -r project_path; do basename "$project_path"; done \
    | python3 -c 'import json, sys; print(json.dumps([line.strip() for line in sys.stdin if line.strip()]))'
}

detect_all() {
  local oauth="" pty="" branch="" projects="" timestamp=""
  oauth="$(detect_oauth_states)"
  pty="$(detect_pty_resource)"
  branch="$(detect_branch_state)"
  projects="$(detect_existing_projects)"
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python3 - "$oauth" "$pty" "$branch" "$projects" "$timestamp" <<'PY'
import json
import sys

oauth = json.loads(sys.argv[1])
pty = json.loads(sys.argv[2])
branch = json.loads(sys.argv[3])
projects = json.loads(sys.argv[4])
timestamp = sys.argv[5]

print(json.dumps({
    "oauth": oauth,
    "pty": pty,
    "branch": branch,
    "existing_projects": projects,
    "timestamp": timestamp,
}))
PY
}
