# Communication & Handoff Protocol

Shared reference for all specialist seats. Planner: see TOOLS/handoff.md for commands.

## Source of Truth

- `TODO.md`, `DELIVERY.md`, and handoff receipts are the durable source of truth
- tmux/chat messages only wake the next seat; they are not durable state
- always re-read `TODO.md` at session start; do not rely on chat summary

## Task Identity Fields

| Field | Meaning |
|---|---|
| `source` | Seat that dispatched this task |
| `reply_to` | Seat that should receive your completion |
| `task_id` | Stable ID used in all receipts and logs |

Always complete to the `reply_to` seat, not the `source`.

## Seat-to-Seat Notify

### Canonical transport
```bash
/path/to/send-and-verify.sh <session-name> '<message>'
# multi-project: pass --project <name>
```

### Recommended alternative (ad hoc reminders/unblocks)
```bash
python3 notify_seat.py --profile <profile> --source <you> --target <seat> \
  --task-id <ID> --message '<message>'
```

### Raw tmux send-keys: NEVER
Treat raw `tmux send-keys` as a **protocol violation**.
- If transport script is unavailable: send text, wait 1 s, send `Enter`, verify not stranded.
- Reviewer: if you detect raw tmux send-keys in a diff or bash log targeting another seat, set `Verdict: CHANGES_REQUESTED` and require fix via `complete_handoff.py --user-summary`.

## Consumed ACK

Before routing a specialist result to the next hop, stamp a durable ACK:
```bash
python3 complete_handoff.py \
  --profile <profile> \
  --source <specialist-seat> \
  --target <planner-seat> \
  --task-id <ID> \
  --ack-only
```

A `Consumed:` ACK records that the delivery was read. It does NOT finish the chain.

## Canonical Verdicts (reviewer must include one)

| Verdict | Meaning |
|---|---|
| `APPROVED` | Ready to land as-is |
| `APPROVED_WITH_NITS` | Land with minor fixes, no re-review needed |
| `CHANGES_REQUESTED` | Must be revised and re-reviewed |
| `BLOCKED` | External blocker; cannot proceed without resolution |
| `DECISION_NEEDED` | Needs planner / user decision before continuing |

Include as `Verdict: APPROVED` in `DELIVERY.md` and pass `--verdict APPROVED` to `complete_handoff.py`.

## DELIVERY.md Required Fields

```
task_id: <ID>
owner: <your-seat>
target: <reply_to-seat>
status: completed | rejected | needs_revision
Verdict: APPROVED             # reviewer only
FrontstageDisposition: AUTO_ADVANCE | USER_DECISION_NEEDED
UserSummary: <short plain-language summary for the user>
```

## Completion Handoff

```bash
python3 complete_handoff.py \
  --profile <profile> \
  --source <your-seat> \
  --target <reply_to-seat> \
  --task-id <ID> \
  --title '<TITLE>' \
  --summary '<DELIVERY_SUMMARY>' \
  [--verdict APPROVED]                          # reviewer only
  [--frontstage-disposition AUTO_ADVANCE]       # planner closing to koder
  [--user-summary '<SHORT_USER_SUMMARY>']
```
