#!/usr/bin/env bash
set -euo pipefail

privacy_file="${CLAWSEAT_PRIVACY_FILE:-$HOME/.agents/memory/machine/privacy.md}"

warn() {
  printf 'privacy-check: warn: %s\n' "$*" >&2
}

if [[ ! -e "$privacy_file" ]]; then
  warn "privacy KB missing: $privacy_file; skipping"
  exit 0
fi

if [[ ! -r "$privacy_file" ]]; then
  warn "privacy KB is not readable: $privacy_file; skipping"
  exit 0
fi

patterns=()
while IFS= read -r line; do
  line="${line%$'\r'}"
  [[ "$line" == BLOCK:* ]] || continue
  pattern="${line#BLOCK:}"
  pattern="${pattern#"${pattern%%[![:space:]]*}"}"
  pattern="${pattern%"${pattern##*[![:space:]]}"}"
  [[ -n "$pattern" ]] && patterns+=("$pattern")
done <"$privacy_file"

if [[ ${#patterns[@]} -eq 0 ]]; then
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  warn "git not found; skipping"
  exit 0
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  warn "not inside a git worktree; skipping"
  exit 0
fi

diff_file="$(mktemp "${TMPDIR:-/tmp}/clawseat-privacy-diff.XXXXXX")"
trap 'rm -f "$diff_file"' EXIT

if ! git diff --cached --no-ext-diff --unified=0 >"$diff_file"; then
  warn "unable to read staged diff; skipping"
  exit 0
fi

if [[ ! -s "$diff_file" ]]; then
  exit 0
fi

regex_is_valid() {
  local pattern="$1"
  local rc=0
  set +e
  printf '' | grep -E -q -- "$pattern" >/dev/null 2>&1
  rc=$?
  set -e
  [[ "$rc" -ne 2 ]]
}

line_matches() {
  local pattern="$1" line="$2"
  if regex_is_valid "$pattern"; then
    printf '%s\n' "$line" | grep -E -q -- "$pattern"
  else
    printf '%s\n' "$line" | grep -F -q -- "$pattern"
  fi
}

hit=0
for pattern in "${patterns[@]}"; do
  current_path="<unknown>"
  while IFS= read -r diff_line; do
    case "$diff_line" in
      "+++ b/"*)
        current_path="${diff_line#+++ b/}"
        ;;
      +*)
        [[ "$diff_line" == +++* ]] && continue
        content="${diff_line:1}"
        if line_matches "$pattern" "$content"; then
          printf 'privacy-check: blocked pattern %q found in staged diff: %s\n' "$pattern" "$current_path" >&2
          hit=1
        fi
        ;;
    esac
  done <"$diff_file"
done

exit "$hit"
