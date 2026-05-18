#!/usr/bin/env bash
# manual: ./tests/test_solo_b_e2e_smoke.sh
# NOT for CI (spawns real tmux sessions if run without --dry-run guard changes)
set -euo pipefail

PROJECT="solo-b-smoke-$(date +%s)"
echo "Starting solo-B smoke test for project: $PROJECT"

bash scripts/install.sh --dry-run --project "$PROJECT" --template clawseat-solo \
  --provider oauth 2>&1 | grep -E "PENDING_SEATS|planner|builder|memory"

echo "PASS: dry-run smoke test for solo-B"
