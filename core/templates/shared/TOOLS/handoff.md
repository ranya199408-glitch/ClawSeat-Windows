# Dispatch, ACK & Closeout Commands

Replace `<PROFILE>` with the resolved profile path for this project.

## Dispatch to a Specialist

```bash
python3 <HARNESS_SCRIPTS>/dispatch_task.py \
  --profile <PROFILE> \
  --source planner \
  --target <TARGET_SEAT> \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --objective '<OBJECTIVE>' \
  --test-policy UPDATE \
  --intent <INTENT_KEY> \
  --reply-to planner
```

See `TOOLS/intent.md` for the `--intent` key mapping.

## Consumed ACK (after reading specialist delivery)

```bash
python3 <HARNESS_SCRIPTS>/complete_handoff.py \
  --profile <PROFILE> \
  --source <SPECIALIST_SEAT> \
  --target planner \
  --task-id <TASK_ID> \
  --ack-only
```

A `Consumed:` ACK records that you read the delivery. It does NOT finish the chain.

## Return Chain Result to Koder

```bash
python3 <HARNESS_SCRIPTS>/complete_handoff.py \
  --profile <PROFILE> \
  --source planner \
  --target koder \
  --task-id <TASK_ID> \
  --title '<TITLE>' \
  --summary '<CHAIN_SUMMARY>' \
  --frontstage-disposition AUTO_ADVANCE \
  --user-summary '<SHORT_USER_SUMMARY>'
```

Use `--frontstage-disposition USER_DECISION_NEEDED` when a real user decision is required.

## Unblock / Reminder to Koder

```bash
python3 <HARNESS_SCRIPTS>/notify_seat.py \
  --profile <PROFILE> \
  --source planner \
  --target koder \
  --task-id <TASK_ID> \
  --kind unblock \
  --reply-to planner \
  --message '<MESSAGE>'
```

## Seat Needed Signal

When a required specialist is not running, return to koder before dispatching:

```bash
python3 <HARNESS_SCRIPTS>/complete_handoff.py \
  --profile <PROFILE> \
  --source planner \
  --target koder \
  --task-id <TASK_ID> \
  --title 'seat_needed: <seat>' \
  --summary 'Need <seat> running before dispatching <TASK_ID>. Pausing.' \
  --frontstage-disposition USER_DECISION_NEEDED \
  --user-summary 'Waiting for koder to launch the required seat.'
```

Resume when koder sends `seat_ready: <seat>`.

## Koder Consume ACK

When planner closeout arrives at koder with `frontstage_disposition: AUTO_ADVANCE`, koder must immediately prune its own TODO entry via `--ack-only`. No user notification needed.

```bash
# When planner closeout arrives with AUTO_ADVANCE:
python3 <HARNESS_SCRIPTS>/complete_handoff.py \
  --profile <PROFILE> \
  --source planner --target koder \
  --task-id <TASK_ID> \
  --ack-only
```

For `USER_DECISION_NEEDED`: do NOT auto-ack. Hold the entry, relay summary to user, and wait.

For Koder v2, routing and user-notification policy live in `IDENTITY.md` and
the `clawseat-koder` skill.
