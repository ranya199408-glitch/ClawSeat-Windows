# Chain Protocol

Default chain shape:

- `user -> frontstage -> planner -> specialist -> planner -> ... -> frontstage -> user`

One common project mapping is:

- `user -> koder -> planner -> specialist -> planner -> ... -> koder -> user`

## Dispatch protocol

1. write target `TODO`
   - target `TODO.md` must include:
     - `task_id`
     - `source`
     - `reply_to`
   - use `scripts/dispatch_task.py` as the default dispatch path instead of
     hand-writing `TODO.md`, `TASKS.md`, or `STATUS.md`
2. update project task/state docs
3. notify via `send-and-verify`
   - the notification text should explicitly include:
     - who dispatched the task
     - who the target seat is
     - who the target seat should reply to when complete
   - in a multi-project setup, never resolve a bare seat id with
     `agentctl.sh session-name planner`
   - use either the canonical tmux session name directly, or pass
     `--project <project>` to the transport helper
   - prefer `scripts/notify_seat.py`
     for ad hoc reminders or unblock notices that are not full dispatches
   - this is the default transport; do not use raw `tmux send-keys` unless the
     transport script is unavailable
   - the canonical transport contract is fire-and-forget:
     - send the text via `tmux send-keys -l`
     - wait 0.3 seconds
     - send `Enter` three times with 0.2 second intervals (flushes any
       stuck prior input from the same pane)
     - exit 0 on transport-level success (pane is live); exit 2 is
       reserved for a future "target seat intentionally skipped" signal
   - callers do NOT receive a message-submission confirmation; the
     3-Enter flush is the correctness mechanism, not a verify step
   - if a fallback is unavoidable, replicate the transport contract
     above verbatim
   - Previously this contract included a verify-stranded-input step;
     commit d7f6e0d relaxes that to fire-and-forget with 3-Enter flush.
     Rationale: Claude TUI panes absorb excess Enter as no-op during
     processing, so stuck input is self-clearing without verify.
4. write a handoff receipt

Default policy:

- frontstage -> planner dispatch should normally go through
  `scripts/dispatch_task.py`
- planner -> specialist dispatch should normally go through
  `scripts/dispatch_task.py`
- when a Feishu group is configured, `dispatch_task.py` also emits the planner
  task-release broadcast to the initial bound group instead of leaving that as
  a manual side effect
- that release broadcast is operational telemetry, not a control packet for
  `koder`; only `OC_DELEGATION_REPORT_V1` should be treated as a machine-readable
  delegation receipt on the user channel
- if the helper is unavailable and a fallback is unavoidable, the operator
  must still leave all four artifacts:
  - `TODO.md` with `source` and `reply_to`
  - `TASKS.md` update
  - `STATUS.md` update
  - machine-readable dispatch receipt

## Seat launch protocol

Before frontstage starts any non-frontstage seat, it must first summarize to
the user:

- which harness/profile will be used
- which seat/role is being launched
- which tool/runtime will be used
- which auth mode and provider/model family will be used

Only after the user confirms may frontstage actually launch the seat.

## Completion protocol

1. specialist writes `DELIVERY`
   - `DELIVERY.md` must include:
     - `task_id`
     - `owner`
     - `target`
2. specialist notifies planner
   - the notification text should explicitly include:
     - who completed the task
     - who should consume it
   - in a multi-project setup, the transport must resolve the target seat with
     an explicit project or canonical session name
   - use the same `send-and-verify` transport rule as dispatch
3. planner writes durable `Consumed:` ACK
4. planner decides the next hop

The durable `Consumed:` ACK is only the handoff-read marker. It is not the end
of the chain. If the delivery resolves the task, planner must immediately move
on to the planner -> frontstage closeout helper and emit the matching
`OC_DELEGATION_REPORT_V1` / `complete_handoff.py` receipt instead of parking on
the ACK.

## Planner -> frontstage closeout

When the active loop owner returns a chain result to frontstage:

1. planner uses `scripts/complete_handoff.py` as the default closeout path
   - do not hand-roll a planner closeout with ad hoc file edits unless the
     helper is unavailable
2. planner writes `DELIVERY`
   - `DELIVERY.md` must include:
     - `task_id`
     - `owner`
     - `target`
     - `FrontstageDisposition: AUTO_ADVANCE | USER_DECISION_NEEDED`
     - `UserSummary: ...` in short plain language
   - if `FrontstageDisposition: USER_DECISION_NEEDED`, also include:
     - `NextAction: ...`
3. planner notifies frontstage using the same `send-and-verify` transport rule
4. planner writes a machine-readable handoff receipt
5. planner refreshes the frontstage inbox
   - write the current frontstage `TODO.md` so koder/frontstage has a durable
     current-task anchor even if the live TUI compacts or restarts
   - the frontstage inbox item should carry:
     - `task_id`
     - `source`
     - `reply_to`
     - `FrontstageDisposition`
     - `UserSummary`
6. frontstage reads the planner receipt and:
   - gives the user a short, easy-to-understand summary
   - auto-advances by default when the disposition is `AUTO_ADVANCE`
   - asks the user to decide only when the disposition is `USER_DECISION_NEEDED`
   - if the chain already resolved at planner, the receipt should have been
     written before the planner session could forget the closeout step
7. if a Feishu group is configured, planner also emits the closeout broadcast
   to the same initial bound group when the receipt lands, so the group sees
   both release and wrap-up without requiring a separate manual post
   - when the closeout is intended to wake `koder` through the user channel,
     this must be an `OC_DELEGATION_REPORT_V1` envelope sent with
     `lark-cli --as user`, not just an unstructured status line
8. when frontstage sees the stage wrap-up, it should read the linked delivery
   trail, reconcile the stage result, and update the project docs before
   reporting the final status to the user

## Persistent planner state: PLANNER_BRIEF.md

`DELIVERY.md` is per-handoff. In addition, planner maintains a persistent
state document: `PLANNER_BRIEF.md` (at `{tasks_root}/planner/PLANNER_BRIEF.md`).

`PLANNER_BRIEF.md` is the only planning window that frontstage reads. It
carries:

- `status`: current chain/planner state
- `frontstage_disposition`: the machine-readable control field that drives
  frontstage behavior (same vocabulary as `DELIVERY.md` FrontstageDisposition)
- `用户摘要`: user-facing Chinese summary of the current state

Frontstage reads `PLANNER_BRIEF.md` through the adapter, not by parsing
specialist `DELIVERY.md` files directly. This keeps the frontstage layer
thin and disposition-driven.

When planner writes a `DELIVERY.md` aimed at frontstage via
`complete_handoff.py`, it should also update `PLANNER_BRIEF.md` to reflect
the new state so that patrol and subsequent reads stay consistent.

## Planner decision gates

If planner pauses for user input before the chain is complete, that decision
must also be made visible on the Feishu user-identity bridge instead of staying
only in the TUI.

- emit `OC_DELEGATION_REPORT_V1` immediately when the pause is caused by a
  user gate
- use `report_status=needs_decision`
- use `decision_hint=ask_user`
- use `user_gate=required`
- use `next_action=ask_user`
- keep the human-readable tail short and explicit so `koder` can surface the
  same question to the user without inventing new semantics

This is an interim decision report, not a substitute for the final closeout.
Once the user decides, planner should continue the chain and later send the
normal `AUTO_ADVANCE` or `finalize_chain` closeout.

Default policy:

- planner auto-advances most of the time
- planning memos and execution plans should also default to `AUTO_ADVANCE`
  once the current scope is already accepted; do not wait for a second
  frontstage approval unless the task spec or the user explicitly created a
  plan gate
- escalate to the user only for genuine product, scope, risk, seat, or model/auth choices
- when using the Feishu user-identity bridge, `koder` must parse the
  `OC_DELEGATION_REPORT_V1` envelope instead of relying on sender identity; see
  `references/feishu-delegation-report.md`

## Mandatory review gate

Planner may self-close only when a task is truly self-contained and does not
change repository artifacts or protocol semantics. As soon as a task touches
docs, templates, skills, protocol text, config, or source code, planner must
treat it as review-required:

- if implementation is needed, route through `builder-1` first
- always route the resulting artifact through `reviewer-1` before frontstage
  closeout
- do not auto-advance a docs/templates/protocol change without a reviewer
  verdict unless the user explicitly exempted review
- pure investigation or analysis tasks may still auto-advance when they produce
  no repository change

This keeps planner from silently self-closing edits that should have been
cross-checked by another seat.

## Handoff state machine

- `assigned`
- `notified`
- `consumed`

Only `assigned + notified + consumed` counts as healthy.

## Generic reminders / unblock notices

- frontstage or planner should use `scripts/notify_seat.py`
  for one-off notices instead of raw tmux
- if the notice is tied to a task, include `--task-id` so the transport leaves
  a receipt

## Review canonical verdicts

- `APPROVED`
- `APPROVED_WITH_NITS`
- `CHANGES_REQUESTED`
- `BLOCKED`
- `DECISION_NEEDED`

Review outputs must carry a canonical `Verdict:` field so the planner does not
have to infer routing from prose.
