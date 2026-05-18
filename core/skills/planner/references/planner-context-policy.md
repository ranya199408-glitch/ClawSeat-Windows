# Planner Context Policy

Planner is the workflow orchestrator and keeps cross-task decision context.

- `[CLEAR-REQUESTED] FORBIDDEN` for planner.
- `[COMPACT-REQUESTED] ONLY` for planner context management.
- Trigger compact at a cross-phase boundary or when context usage is > 80%.
- Compact summaries must preserve active task ids, dispatch decisions,
  blockers, owner assignments, and pending reviews.
