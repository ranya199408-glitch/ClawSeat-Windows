# Seat Lifecycle Rules

## Planner's Role: Signal Only

Seat lifecycle is **koder's responsibility, NOT planner's**.

- Do NOT run `start_seat.py` yourself from inside a planner tmux seat.
- Do NOT run `window open-monitor` from inside a tmux seat — it may close the tab you are running in.
- Do NOT attempt to reconfigure (switch tool/auth/provider) from planner — that is koder's job.

## Seat Needed Protocol

If a specialist you need is down or missing, return a `seat_needed` signal to koder and pause:

```bash
python3 <HARNESS_SCRIPTS>/complete_handoff.py \
  --profile <PROFILE> \
  --source planner \
  --target koder \
  --task-id <TASK_ID> \
  --title 'seat_needed: <seat>' \
  --summary 'Need <seat> running before dispatching. Pausing.' \
  --frontstage-disposition USER_DECISION_NEEDED \
  --user-summary 'Waiting for koder to launch the required seat.'
```

Resume when koder sends `seat_ready: <seat>`.

## Seat Ready Confirmation

When koder reports a seat is up (`seat_ready: <seat>`), re-read the pending task from
`TODO.md` and dispatch immediately — do not wait for a second nudge.

## Monitor Window

Ask koder (frontstage) to open the monitor window, or let the user run it from an
external terminal:
```bash
python3 <AGENT_ADMIN> window open-monitor <project>
```

Never run `window open-monitor` from inside your own tmux seat.
