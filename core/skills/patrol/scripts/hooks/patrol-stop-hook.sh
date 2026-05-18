#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

payload="$(cat || true)"
[[ -n "$payload" ]] || exit 0
command -v feishu >/dev/null 2>&1 || exit 0

parsed="$(PATROL_HOOK_PAYLOAD="$payload" "$PYTHON_BIN" - <<'PY' || true
import json, re, shlex, sys
from pathlib import Path

try:
    import os
    payload = json.loads(os.environ.get("PATROL_HOOK_PAYLOAD", "") or "{}")
except json.JSONDecodeError:
    raise SystemExit(0)
msg = str(payload.get("last_assistant_message", "") or "")
match = re.search(r"\[(?:PATROL|QA)-NOTIFY:([^\]]+)\]", msg)
if not match:
    raise SystemExit(0)
attrs = {}
for token in match.group(1).split(","):
    if "=" not in token:
        raise SystemExit(0)
    key, value = token.split("=", 1)
    attrs[key.strip()] = value.strip()
project = attrs.get("project", "")
scope = attrs.get("scope", "")
if not project or scope not in {"patrol", "test"}:
    raise SystemExit(0)
summary = Path.home() / ".agents" / "memory" / "projects" / project / "patrol" / "_summary.md"
print("PROJECT=" + shlex.quote(project))
print("SCOPE=" + shlex.quote(scope))
print("HIGH=" + shlex.quote(attrs.get("high", "0")))
print("MEDIUM=" + shlex.quote(attrs.get("medium", "0")))
print("LOW=" + shlex.quote(attrs.get("low", "0")))
print("SUMMARY=" + shlex.quote(str(summary)))
PY
)"
[[ -n "$parsed" ]] || exit 0
eval "$parsed"

session="$(tmux display-message -p '#S' 2>/dev/null || echo unknown)"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
body="[PATROL scope=${SCOPE}]
Patrol ${SCOPE} summary for ${PROJECT}: high=${HIGH} medium=${MEDIUM} low=${LOW}"
if [[ -f "${SUMMARY:-}" ]]; then
  body="${body}"$'\n\n'"$(cat "$SUMMARY" 2>/dev/null || true)"
fi
body="${body}"$'\n\n---\n'"_via Patrol @ ${ts} | project=${PROJECT} | session=${session}_"

feishu "$body" >/dev/null 2>&1 || true
exit 0
