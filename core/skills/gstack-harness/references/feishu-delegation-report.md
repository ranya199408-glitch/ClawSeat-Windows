# Feishu Delegation Report

When `planner` needs to wake `koder` through a Feishu group using `lark-cli
--as user`, sender identity is no longer trustworthy. The group will see the
message as coming from the human user, not from a seat.

Therefore `koder` must not infer provenance from the sender. It should only
auto-act on a strict structured envelope:

```text
[OC_DELEGATION_REPORT_V1]
project=<project>
lane=<planning|builder|reviewer|patrol|designer|frontstage>
task_id=<TASK_ID>
dispatch_nonce=<nonce>
report_status=<in_progress|done|needs_decision|blocked>
decision_hint=<hold|proceed|ask_user|retry|escalate|close>
user_gate=<none|optional|required>
next_action=<wait|consume_closeout|ask_user|retry_current_lane|surface_blocker|finalize_chain>
summary=<single-line summary>
[/OC_DELEGATION_REPORT_V1]
```

Optional human-readable text may appear after the closing marker. `koder`
should ignore it for machine parsing.

`planner` must emit this envelope not only for final closeouts, but also for
any user-facing decision gate that would otherwise remain trapped in the TUI.
In practice that means:

- `report_status=needs_decision`
- `decision_hint=ask_user`
- `user_gate=required`
- `next_action=ask_user`

This keeps the user-visible decision path aligned with the same Feishu bridge
that carries regular closeouts.

## Final Minimal Field Set

| Field | Meaning |
|---|---|
| `project` | Prevents cross-project drift in shared groups |
| `lane` | Identifies which execution lane produced the receipt; this is not sender identity |
| `task_id` | Stable task anchor |
| `dispatch_nonce` | Per-delegation nonce used to reject stale or replayed group messages |
| `report_status` | Current state of the lane result |
| `decision_hint` | High-level routing recommendation for `koder` |
| `user_gate` | Whether user confirmation is required before auto-advance |
| `next_action` | Finite action token that `koder` can map into its state machine |
| `summary` | One-line Chinese summary for both logs and user-visible recovery |

`source=planner` is intentionally forbidden in this envelope. The message is
sent through the user's Feishu identity, so the protocol must be lane-based,
not persona-based.

## Parsing Rules

`koder` should only auto-consume a group message when all of the following are
true:

1. the message contains `[OC_DELEGATION_REPORT_V1]`
2. `project` matches the active project
3. `task_id` matches an active delegation chain
4. `dispatch_nonce` matches the current outstanding delegation
5. `lane` is recognized
6. all enum values are valid

If any check fails, treat the message as normal user chat.

## Decision State Machine

| report_status | decision_hint | user_gate | next_action | Expected `koder` behavior |
|---|---|---|---|---|
| `in_progress` | `hold` | `none` or `optional` | `wait` | Record progress only. Do not reroute. |
| `done` | `proceed` | `none` | `consume_closeout` | Read the linked delivery trail, update project docs, and continue the chain. |
| `done` | `close` | `none` | `finalize_chain` | Summarize, reconcile docs, and finish the chain. |
| `needs_decision` | `ask_user` | `required` or `optional` | `ask_user` | Turn the receipt into a short user question; do not auto-dispatch. |
| `blocked` | `retry` | `none` or `optional` | `retry_current_lane` | Retry once or hand back to the same lane with the blocker context attached. |
| `blocked` | `escalate` | `optional` or `required` | `surface_blocker` | Surface the blocker to the user/operator without inventing a next hop. |

## Closeout Mapping

For the existing `planner -> frontstage` closeout path:

- `FrontstageDisposition: AUTO_ADVANCE`
  - `report_status=done`
  - `decision_hint=proceed`
  - `user_gate=none`
  - `next_action=consume_closeout`

- `FrontstageDisposition: USER_DECISION_NEEDED`
  - `report_status=needs_decision`
  - `decision_hint=ask_user`
  - `user_gate=required`
  - `next_action=ask_user`

This mapping lets the Feishu group receipt remain small while still telling
`koder` whether to continue automatically or ask the user to decide.
