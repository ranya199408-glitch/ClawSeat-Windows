# Heartbeat Policy

Recurring heartbeat belongs only to the frontstage-supervisor seat.

Default cadence is every 15 minutes unless a project profile explicitly narrows
it for a temporary debugging window.

## Duties

- patrol chain state
- detect missing `Consumed:` ACKs
- detect stalled deliveries or blocked seats
- detect resource blockers such as usage-limit / subscription / capacity failures
- append patrol learnings when live pane judgment conflicts with durable task facts
- decide whether the active loop owner needs a reminder

Heartbeat should stay script-first and context-light:

- run the classifier/patrol scripts before reading broad project docs
- do not enter plan mode for routine heartbeat polls
- only load extra docs when scripted facts are ambiguous or contradictory

## Guardrails

- heartbeat does not dispatch downstream work
- heartbeat does not rewrite the execution plan
- heartbeat may unblock procedural waits
- execution decisions remain with the planner-dispatcher
- when a seat hits `usage_limit` or similar quota blockers, including
  `429 Too Many Requests` or `exceeded retry limit`, heartbeat should treat it
  as `BLOCKED`, not ordinary `STALLED`
- when pane state later proves stale or contradictory to `TASKS.md` /
  durable `Consumed:` ACKs, heartbeat should record that as a patrol learning
  under `tasks_root/patrol/learnings.jsonl`

## Provisioning

- provision only for seats allowed by the project profile
- in most projects, heartbeat is reserved for the frontstage seat such as `koder`
- installation must be backed by a verified receipt, not only a scheduler lock
- on a fresh Claude seat, heartbeat may stay pending until the user manually
  completes first-run onboarding in the TUI
- once onboarding is complete, the operator should resume control and re-run
  heartbeat provisioning
- auto-provision must not queue `/loop` while Claude is still showing onboarding
  or first-run safety prompts; wait for a stable prompt first
