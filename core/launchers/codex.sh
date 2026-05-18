#!/usr/bin/env bash
# Convenience wrapper: launch Codex via agent-launcher.sh.
set -euo pipefail
exec "$(dirname "$0")/agent-launcher.sh" --tool codex "$@"
