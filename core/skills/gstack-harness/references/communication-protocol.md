# Communication Protocol

This reference defines how ClawSeat seats send operational messages to each
other. It is the protocol layer. State transitions and assignment rules live in
`core/skills/planner/references/collaboration-rules.md`.

## 1. 通信原则 / Communication Principles

- Communication is all-to-all peer-to-peer between live seats.
- The sender is responsible for choosing the correct target seat.
- The receiver is responsible for reading durable task files before acting.
- `send-and-verify.sh` is the only standard transport for seat-to-seat wakeups.
- Never use raw `tmux send-keys` for normal protocol messages.
- Summary: all-to-all peer-to-peer, send-and-verify 唯一标准 transport, 永不
  raw tmux send-keys.
- If the transport helper is unavailable, the fallback must reproduce its
  contract: send literal text, wait briefly, send Enter, and verify the message
  did not remain stranded in the input buffer.
- Chat text is a wakeup signal; durable truth lives in TODO, DELIVERY, STATUS,
  task receipts, and project memory.
- A message may be lost or compacted; a durable file must still let the receiver
  reconstruct the requested action.
- Every dispatch or delivery message must name source, intent, task id, and
  expected next action.
- In multi-project mode, always include `--project <project>` or a canonical
  session name.

## 2. Transport Contract

Standard command shape:

```bash
<CLAWSEAT_REPO>/core/shell-scripts/send-and-verify.sh \
  --project <project> <target-seat-or-session> "<message>"
```

Rules:

- Target a role/seat only when the project is explicit.
- Target a canonical tmux session only when the session string is already
  unambiguous.
- Do not hand-write transport with `tmux send-keys`.
- Do not use Feishu, comments, or terminal paste as the durable source of truth.
- When a helper writes a receipt, link that receipt in delivery or status docs.

## 3. Push 主路径 / Push Main Path

Push is the preferred path.

1. The current owner completes a step or reaches a blocker.
2. The owner updates durable state for that step.
3. The owner reads `notify_on_done` for the step or task.
4. The owner sends a protocol message to each listed target with
   `send-and-verify.sh`.
5. The notified target reads durable state before acting.
6. The notified target writes a durable consumed ACK when the message changes
   ownership or state.

Push messages must be short. They should not embed the entire plan or delivery.
They should point to the durable file that contains the full details.

## 4. Pull 兜底 / Pull Fallback

Pull exists only as a recovery mechanism when a push did not arrive or a seat
has restarted.

Canonical command:

```bash
agent_admin task list-pending --owner-role <r>
```

Rules:

- Use pull after restart, compact recovery, or suspected missed notification.
- Pull does not replace push; owners still notify `notify_on_done`.
- A pulled task must still be consumed through the normal durable ACK path.
- If pull reveals stale work, planner reconciles it before dispatching more.

## 5. Message format / Message Format

Canonical one-line format:

```text
[<source>] <intent>: task <id> step <N> done; <next-action-hint>
```

Fields:

- `<source>` is the sender seat or role.
- `<intent>` is one of the intent enum values below.
- `<id>` is the durable task id.
- `<N>` is the step number when the message is step-scoped.
- `<next-action-hint>` tells the receiver what to read or do next.

Examples:

```text
[planner] dispatch: task t1-foundation-ref-docs step 1 done; read TODO.md and implement docs
[builder] delivery: task t1-foundation-ref-docs step 1 done; read DELIVERY.md
[reviewer] consumed: task t1-foundation-ref-docs step 2 done; verdict recorded
```

## 6. Intent enum / Intent Enum

The intent enum has exactly these eight protocol intents.

### brief-handoff

- Direction: memory -> planner.
- Meaning: memory has converted intake into a planner-readable brief.
- Durable anchor: planner TODO or brief handoff receipt.

### dispatch

- Direction: planner -> specialist.
- Meaning: planner assigned executable work to a specialist.
- Durable anchor: target TODO plus task receipt.

### delivery

- Direction: specialist -> planner.
- Meaning: specialist completed or blocked assigned work.
- Durable anchor: target `DELIVERY.md`.

### verdict-request

- Direction: planner -> memory.
- Meaning: planner needs memory or user-facing decision authority.
- Durable anchor: planner status plus decision context.

### verdict

- Direction: memory -> planner.
- Meaning: memory supplied the requested decision or user verdict.
- Durable anchor: memory decision record or planner delivery.

### consumed

- Direction: any -> any.
- Meaning: receiver read the durable artifact and accepted ownership of the next
  action.
- Durable anchor: status, delivery trail, or handoff receipt.

### patrol-finding

- Direction: patrol -> planner.
- Meaning: scheduled patrol found drift or a condition requiring triage.
- Durable anchor: patrol finding record.

### escalation

- Direction: any -> memory/user.
- Meaning: automation lacks authority, context, or safety to continue.
- Durable anchor: decision request and reason.

## 7. 派单 vs 派工严格区分 / Dispatch vs Assignment Boundary

ClawSeat distinguishes 派单 from 派工.

派单:

- Memory holds 派单 authority.
- Memory performs brief authoring and forwards the brief to planner.
- Memory does not personally send specialist dispatch messages.

派工:

- Planner holds 派工 authority.
- Planner performs `assign_owner`, writes target TODO, and sends dispatch
  transport directly to specialists.
- Planner tracks specialist delivery and downstream review.

Forbidden boundary crossings:

- Memory never sends a dispatch directly to builder, reviewer, patrol, or
  designer.
- Planner never replaces memory intake or final user-facing decision ownership.
- Specialists never self-assign new chain work.

## 8. Marker conventions / Marker Conventions

Markers are literal hints carried in task or message text.

- `[CLEAR-REQUESTED]` asks the target to clear only after durable state is safe.
- `[COMPACT-REQUESTED]` asks the target to compact after preserving active state.
- `[DELIVER:seat=X]` asks a specialist to deliver to the named seat.
- `[PATROL-NOTIFY:scope=patrol]` routes a patrol-scoped notification.
- `[QA-NOTIFY]` is an alias for patrol notification when legacy text uses that
  shorter marker.

Markers do not override authority. A marker that conflicts with role boundary
must be escalated instead of obeyed.

## 9. Cross-tool delivery / Cross-Tool Delivery

Claude Code:

- Stop hook may run completion automation automatically.
- Delivery still needs durable state and a protocol message when ownership
  changes.

Gemini and Codex:

- These tools must explicitly call `complete_handoff.py` when closing a handoff.
- They must still notify the target with `send-and-verify.sh` after the durable
  receipt exists.

All tools:

- Write `DELIVERY.md` before notifying.
- Include status, changed files, tests, risks, and commit information when the
  role contract requires them.

## 10. Privacy gate / Privacy Gate

Before transport, `send-and-verify.sh` starts the privacy gate.

- Read machine privacy policy from `~/.agents/memory/machine/privacy.md`.
- Treat each `BLOCK` pattern as a deny rule.
- Enforce the machine/privacy.md BLOCK pattern gate before sending.
- Grep outgoing message text for blocked patterns.
- Reject the send when a block pattern matches.
- Do not bypass the gate by using raw tmux, manual paste, or another channel.

If the privacy gate blocks a message:

- Remove or summarize sensitive content.
- Link to a durable local file if the receiver can read it safely.
- Escalate to memory/user when no safe summary exists.
