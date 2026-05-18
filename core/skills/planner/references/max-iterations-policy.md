# Max Iterations Policy

Default `max_iterations` is 3 when a workflow.md step does not set an explicit
limit.

| Failure type | Action |
| --- | --- |
| Command error (non-zero exit) | Record stderr -> `notify_on_issues` -> `iter++` |
| Test failure | Record output -> `notify_on_issues` (builder loops back) |
| `iter > max_iterations` | `notify_on_blocked` -> `escalate_on_max` seat decides |
| Seat dead (heartbeat stale) | planner restarts via `agent_admin session start-engineer` |
| User decline | `AskUserQuestion` escalate step |
| Skill unavailable | `notify_on_blocked` -> planner checks `skill-catalog` |

Escalation chain:

1. Specialist records evidence and notifies planner.
2. Planner retries or reroutes within the workflow limits.
3. Memory receives unresolved cross-task, user, or authority decisions.
4. Operator is asked only when memory needs a human decision.

Rules:

- Do not hide a failed command by retrying without updating `iter`.
- Do not advance a step to `done` after a failed verification command.
- When the limit is exceeded, stop work and preserve artifacts for the next
  owner instead of continuing locally.
