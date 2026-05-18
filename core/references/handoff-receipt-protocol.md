# Handoff Receipt Protocol

Completion is a mandatory two-step; neither step substitutes for the other.

## Two required steps (不可二选一)

1. Call `complete_handoff.py` — writes the durable `.consumed` receipt to disk. This is the audit record that proves the task closed.
2. Call `send-and-verify.sh` — sends the wake-up notification to `reply_to`. This is transport only and cannot substitute for step 1.

## Failure path

If `complete_handoff.py` fails:
- Do NOT silently proceed to `send-and-verify.sh` alone.
- Escalate to `reply_to` + memory with the failure details.
- Record the error in `artifacts/` before escalating.

## Example (standard closeout)

```bash
python3 "$CLAWSEAT_ROOT/core/skills/gstack-harness/scripts/complete_handoff.py" \
  --profile "$SEAT_PROFILE" \
  --source <seat> \
  --target <reply_to> \
  --task-id <task_id> \
  --verdict <verdict> \
  --title "<title>" \
  --summary "<one-line summary>"

# Then wake up the next seat:
bash "$CLAWSEAT_ROOT/core/shell-scripts/send-and-verify.sh" \
  --project <project> <reply_to> "[<task_id>] done - verdict <verdict>"
```

## Rule summary

完成必须两步，不可二选一: 1. call `complete_handoff.py` 写 durable `.consumed` receipt; 2. then `send-and-verify.sh` wake reply_to. send-and-verify cannot substitute; complete_handoff.py 失败要 escalate 给 reply_to + memory.
