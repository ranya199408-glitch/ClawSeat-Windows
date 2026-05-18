#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="$SCRIPT_DIR/projects_registry.py"

usage() {
  cat >&2 <<'EOF'
usage:
  clawseat projects list [--json] [--active-only]
  clawseat projects show <project>
  clawseat projects unregister <project>
  clawseat projects update <project> [--status active|archived|broken] [--metadata key=value]
EOF
}

if [[ $# -lt 2 || "${1:-}" != "projects" ]]; then
  usage
  exit 2
fi

shift
case "${1:-}" in
  list|show|unregister|update)
    exec python3 "$REGISTRY" "$@"
    ;;
  *)
    usage
    exit 2
    ;;
esac
