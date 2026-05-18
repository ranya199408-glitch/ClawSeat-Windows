# Planner self-closeout protocol

This protocol defines the atomic planner relay that closes a builder task and
immediately hands the chain back to memory.

## Trigger

Run `complete_handoff.py` with:

```bash
complete_handoff.py --source planner --target memory --task-id <id> --status completed --verdict <V> --notify
```

The durable receipt is still the primary relay path. `send-and-verify.sh` is
wake-up only and may follow when a separate nudge is needed.

## Atomic order

1. Rename any incoming `/<task_id>__*__planner.json` receipt to `.json.consumed`.
2. Write `planner/DELIVERY.md`.
3. Persist the planner→memory receipt.
4. Notify memory.

If no incoming builder→planner receipt exists, log that the rename was skipped
and continue.

## Delivery metadata

When planner relays to memory, `planner/DELIVERY.md` should carry the branch,
commit, sweep count, and the one-line summary extracted from builder DELIVERY.

## Escape hatch

`--enforce-planner-self-closeout=false` bypasses the rename and the
planner/DELIVERY write. Use it only when you explicitly accept drift between
`.consumed` receipts and `planner/DELIVERY.md`.
